"""FastAPI service exposing the strikeout-edge model.

Routes:
  GET /health      - liveness + active odds provider
  GET /predict     - single-pitcher calc, season-K/9 multiplier model (v1)
  GET /slate       - ranked +EV edges for a date, multiplier model (v1)
  GET /v2/predict  - single-pitcher calc, v2 ensemble + bridge (unified model)
  GET /v2/slate    - ranked +EV edges for a date, v2 ensemble + bridge
  GET /v2/arb      - cross-book strikeout arbitrage scan
  POST /v2/parlay  - combine per-leg projections into a parlay EV
  GET /backtest    - settle logged predictions vs actual results
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date as date_cls

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from dataclasses import asdict as _asdict

from app.arb_pipeline import scan_arbitrage
from app.backtest.clv import clv_report
from app.backtest.metrics import summarize
from app.model.hedge import hedge_existing_position
from app.backtest.reliability import reliability_report
from app.backtest.calibration_validate import oos_validate
from app.backtest.settle import settle_predictions
from app.config import settings
from app.crypto_predictor import (
    CryptoEventPredictor,
    CryptoEventPrediction,
    PredictionResult,
    predict_crypto_event,
)
from app.ensemble_pipeline import build_slate_ensemble, predict_pitcher_ensemble
from app.log.predictions import log_predictions
from app.parlay_pipeline import LegSpec, build_parlay, suggest_parlays
from app.parlay_matrix import build_parlay_matrix
from app.pipeline import build_slate, predict_pitcher
from app import polymarket_client as pmkt
from app import signals as sig

import time as _time

app = FastAPI(title="Edge AI: Multi-Vertical Prediction Platform", version="2.0.0")

# Allow the Vite dev server (local) and the deployed domain. In production the
# frontend is served same-origin behind nginx (/api/*), so CORS isn't strictly
# needed, but listing the domain keeps direct API calls working too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://strike.perfecthold.online",
        "https://strike.perfecthold.online",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _today() -> str:
    return date_cls.today().isoformat()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "odds_provider": settings.odds_provider,
        "devig_method": settings.devig_method,
        "min_edge": settings.min_edge,
    }


@app.get("/predict")
def predict(
    pitcher: str = Query(..., description="Pitcher name (matched to today's starts)"),
    line: float = Query(..., description="Strikeout line, e.g. 6.5"),
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    over_odds: float | None = Query(None, description="Book American odds for the over"),
    under_odds: float | None = Query(None, description="Book American odds for the under"),
) -> dict:
    try:
        return predict_pitcher(
            pitcher=pitcher,
            line=line,
            date=date or _today(),
            over_odds=over_odds,
            under_odds=under_odds,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/slate")
def slate(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    min_edge: float | None = Query(None, description="Filter: only rows with edge >= this"),
) -> dict:
    target = date or _today()
    result = build_slate(target)

    ok_rows = [r for r in result.rows if r.status == "ok"]
    # Log every evaluated prediction (seed for the future backtest/CLV layer).
    log_predictions([asdict(r) for r in ok_rows], settings.predictions_log)

    rows = [asdict(r) for r in result.rows]
    if min_edge is not None:
        rows = [
            r for r in rows
            if r["status"] == "ok" and r["edge"] is not None and r["edge"] >= min_edge
        ]

    return {
        "date": target,
        "count": len(rows),
        "evaluated": len(ok_rows),
        "skipped": result.skipped,
        "bets": sum(1 for r in rows if r.get("bet")),
        "rows": rows,
    }


@app.get("/v2/predict")
async def predict_v2(
    pitcher: str = Query(..., description="Pitcher name (matched to that day's starts)"),
    line: float = Query(..., description="Strikeout line, e.g. 6.5"),
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    over_odds: float | None = Query(None, description="Book American odds for the over"),
    under_odds: float | None = Query(None, description="Book American odds for the under"),
) -> dict:
    """Single-pitcher prediction via the v2 ensemble (recent form + lineup +
    expected innings + umpire + ...), fed through the Poisson/edge bridge."""
    try:
        return await predict_pitcher_ensemble(
            pitcher=pitcher,
            line=line,
            date=date or _today(),
            over_odds=over_odds,
            under_odds=under_odds,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _v2_log_rows(rows: list[dict], date: str) -> list[dict]:
    """Predictions-log rows from a v2 slate: priced (``ok``) rows only, each with a
    per-row ``date`` and ``bet`` = **card membership** (``selected``).

    This makes the graded record match the dashboard: the flagged bets that
    /backtest and /clv score are exactly the featured card (the diversified,
    one-per-game selections), while every decided row still feeds /calibration.
    """
    return [
        {**r, "date": r.get("date", date), "bet": bool(r.get("selected"))}
        for r in rows
        if r.get("status") == "ok"
    ]


@app.get("/v2/slate")
async def slate_v2(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    min_edge: float | None = Query(None, description="Filter: only rows with edge >= this"),
    log: bool = Query(False, description="Append the slate to the predictions log (bet = card membership). The daily cron sets this; dashboard loads do not."),
    max_bets: int = Query(4, ge=1, description="Card: max bets to flag"),
    max_per_game: int = Query(1, ge=1, description="Card: max bets from one game"),
    select_min_edge: float = Query(0.05, description="Card: min edge to be eligible"),
    select_max_edge: float = Query(0.20, description="Card: cap on edge (above = likely model error)"),
    min_completeness: float = Query(0.5, ge=0, le=1, description="Card: min input-completeness score"),
    kelly_fraction: float | None = Query(
        None, ge=0.25, le=0.5,
        description="Kelly scale: 0.25 (quarter, young model) ... 0.5 (half, proven). Default uses server setting.",
    ),
    sharp_check: bool = Query(
        False,
        description="Veto edges where the model is a market-consensus outlier (costs the wide ~3x quote pull).",
    ),
) -> dict:
    """Ranked +EV pitcher-strikeout edges for a date via the v2 ensemble bridge.

    Also returns a diversified ``card`` of the top ``max_bets`` plays for a small
    bankroll (edge band + per-game cap + input-completeness gate).

    ``kelly_fraction`` scales every stake: keep it at 0.25 (quarter-Kelly) while the
    model is young and its sample small; dial toward 0.5 (half-Kelly) only once the
    track record + calibration justify it. Clamped to [0.25, 0.5]."""
    target = date or _today()
    run_settings = settings
    if kelly_fraction is not None:
        run_settings = settings.model_copy(update={"kelly_fraction": kelly_fraction})
    result = await build_slate_ensemble(
        target,
        max_bets=max_bets,
        max_per_game=max_per_game,
        select_min_edge=select_min_edge,
        select_max_edge=select_max_edge,
        min_completeness=min_completeness,
        settings=run_settings,
        sharp_check=sharp_check,
    )
    result["kelly_fraction"] = run_settings.kelly_fraction
    # The daily cron passes log=true so the graded record equals the dashboard's v2
    # card. Dashboard loads leave log=false, so ordinary views never write the log.
    if log:
        log_predictions(_v2_log_rows(result["rows"], target), settings.predictions_log)
    if min_edge is not None:
        result["rows"] = [
            r for r in result["rows"]
            if r.get("status") == "ok"
            and r.get("edge") is not None
            and r["edge"] >= min_edge
        ]
        result["count"] = len(result["rows"])
    return result


@app.get("/v2/arb")
def arb(
    bankroll: float = Query(100.0, description="Total stake to split across both legs"),
    min_profit_pct: float = Query(0.0, description="Min locked profit fraction, e.g. 0.01 = 1%"),
) -> dict:
    """Scan the current slate for cross-book strikeout arbitrage (same-line two-way).

    Arbs are rare and short-lived — this is an inefficiency detector, not a
    guaranteed-income feed. Each opportunity lists the two books, the stake split,
    and the locked profit.
    """
    return scan_arbitrage(bankroll=bankroll, min_profit_pct=min_profit_pct)


@app.get("/v2/report", response_class=PlainTextResponse)
def latest_report() -> str:
    """Latest weekly grading report (generated by deploy/report.sh cron on the
    server; see app/report.py). Plain text so humans and agents read it as-is."""
    path = Path(settings.lines_csv).parent / "reports" / "report-latest.txt"
    if not path.exists():
        return "no report generated yet — deploy/report.sh cron has not run"
    return path.read_text(encoding="utf-8")


class ParlayLegBody(BaseModel):
    pitcher: str
    line: float
    side: str = Field(..., description="'over' or 'under'")
    odds: float = Field(..., description="Book American odds for this leg's side")
    date: str | None = Field(None, description="YYYY-MM-DD; defaults to the request date")


class ParlayBody(BaseModel):
    legs: list[ParlayLegBody] = Field(..., min_length=1)
    date: str | None = Field(None, description="YYYY-MM-DD; defaults to today")
    max_legs: int = Field(
        3, ge=2, le=4,
        description="Hard cap on legs (2–3 is the variance/vig sweet spot). >max_legs is rejected.",
    )
    log: bool = Field(
        False,
        description="Log each leg to the predictions log so it feeds /calibration",
    )


@app.post("/v2/parlay")
async def parlay(body: ParlayBody) -> dict:
    """Combine per-leg strikeout projections into a parlay EV + stake.

    Each leg's win probability comes from the v2 ensemble projection; you supply
    the book odds. **Hard rules:** legs in the same game are REJECTED (correlated —
    the product would overstate the true probability) and the parlay is capped at
    ``max_legs`` (default 3). Set ``log=true`` to record each leg (as a
    non-flagged prediction) so its probability is later scored by /calibration."""
    specs = [
        LegSpec(pitcher=l.pitcher, line=l.line, side=l.side, odds=l.odds, date=l.date)
        for l in body.legs
    ]
    try:
        return await build_parlay(
            specs, on_date=body.date or _today(), max_legs=body.max_legs, log=body.log
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/v2/parlay/suggest")
async def parlay_suggest(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    max_legs: int = Query(3, ge=2, le=4, description="Max legs per suggested parlay"),
    max_suggestions: int = Query(5, ge=1, le=20, description="How many to return"),
    bankroll: float | None = Query(None, gt=0, description="If set, each suggestion gets a $ recommended stake = its capped Kelly x bankroll"),
) -> dict:
    """Auto-suggest +EV parlays from today's bet card.

    Enumerates 2..``max_legs`` combinations of the day's card legs — which are
    already one-per-game (so independent) and already +EV/confident — evaluates
    each as a parlay, and returns the positive-EV ones ranked by EV per unit.
    Probabilities include the configured shrinkage, so the EV is honest. Never
    parlays same-game legs and never exceeds ``max_legs`` (the hard rules)."""
    return await suggest_parlays(
        date or _today(), max_legs=max_legs, max_suggestions=max_suggestions,
        bankroll=bankroll,
    )


@app.get("/v2/parlay/matrix")
async def parlay_matrix_route(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    bankroll: float | None = Query(None, gt=0, description="Total bankroll (default: server setting)"),
    reserve: float | None = Query(None, ge=0, description="Locked reserve floor (default: server setting)"),
    cycle_days: int | None = Query(None, gt=0, description="Investment cycle length in days (default: server setting)"),
) -> dict:
    """Daily parlay matrix: hard capital control + EV-gated small/medium/large tiers.

    Plans the bankroll (working capital = bankroll − reserve, spread over the cycle
    to a HARD daily budget), pulls today's +EV one-per-game card legs, and builds the
    best parlay per tier. The small/medium tiers only stake a +EV parlay (skipped
    otherwise); the large tier is an explicit, flagged NEGATIVE-EV variance bucket.
    Legs are hard-capped at 6 — the 8–12-leg "lottery" is never built. The output is
    honest: capital control caps the bleed rate, it does not create edge."""
    return await build_parlay_matrix(
        date or _today(),
        total_bankroll=bankroll if bankroll is not None else settings.bankroll,
        reserve_floor=reserve if reserve is not None else settings.reserve_floor,
        cycle_days=cycle_days if cycle_days is not None else settings.cycle_days,
    )


@app.get("/backtest")
def backtest() -> dict:
    """Settle logged predictions vs actual results -> hit rate, ROI, MAE."""
    settled = settle_predictions(settings.predictions_log)
    return _asdict(summarize(settled))


@app.get("/calibration")
def calibration(
    bins: int = Query(10, ge=2, le=50, description="Reliability-curve bucket count"),
) -> dict:
    """Are the model's probabilities honest? Brier, log-loss + reliability curve.

    Unlike /backtest (ROI on flagged bets), this scores EVERY decided prediction:
    when the model claims 70%, does it hit ~70% over a large sample? That's the
    proof a system is calibrated rather than lucky. Reads the same prediction log,
    settles each vs the actual strikeout result, and buckets by claimed
    probability. Pushes and pre-model_prob rows are excluded.
    """
    settled = settle_predictions(settings.predictions_log)
    return _asdict(reliability_report(settled, n_bins=bins))


@app.get("/calibration/validate")
def calibration_validate(
    train_frac: float = Query(0.7, gt=0.5, lt=0.95, description="Fraction of (chronologically) earliest predictions used to fit"),
    bins: int = Query(10, ge=2, le=50, description="Reliability bucket count for ECE"),
) -> dict:
    """Should we turn calibration ON? Out-of-sample test before it touches staking.

    Fits each calibrator (1-param shrink-to-even, 2-param Platt) on the earliest
    ``train_frac`` of decided predictions and scores it on the later, unseen slice
    — the only honest way to tell real correction from fitting small-sample noise.
    Compares held-out Brier/log-loss/ECE vs the uncalibrated baseline and returns a
    deliberately conservative recommendation. READ-ONLY: this never changes staking;
    it produces the evidence for setting PROB_SHRINKAGE (or justifying a Platt flag).
    """
    settled = settle_predictions(settings.predictions_log)
    return _asdict(oos_validate(settled, train_frac=train_frac, n_bins=bins))


@app.get("/v2/hedge")
def hedge(
    stake: float = Query(..., gt=0, description="Amount already staked on the early bet"),
    odds: float = Query(..., description="American odds of your early bet, e.g. 115"),
    hedge_odds: float = Query(..., description="American odds now available on the opposite side"),
    round_to: float = Query(0.0, ge=0, description="Snap the hedge stake to a $ increment (5/10) for camouflage; 0 = exact"),
) -> dict:
    """Lock an existing position: stake to bet the other side to equalise payout.

    For a bet you ALREADY placed (ideally with positive CLV) that the line has
    since moved on. Reports the hedge stake, capital at risk, and the locked
    result — flagging ``risk_free`` only when the two prices form a cross-time arb
    (otherwise it's an honest capped loss, not free money). See /v2/arb for the
    simultaneous two-book scanner.
    """
    return _asdict(hedge_existing_position(stake, odds, hedge_odds, round_to=round_to))


@app.get("/clv")
def clv() -> dict:
    """Closing Line Value: did our flagged bets beat the market's closing price?

    The sharp's truth metric. /backtest asks 'did we profit?' and /calibration
    asks 'are our probabilities honest?'; this asks the price question: across
    every flagged bet we can match to a captured closing line, did we consistently
    buy below where the market closed (positive de-vigged CLV)? That's the one
    academically-supported signal of real edge. Needs closing lines captured near
    first pitch (line_capture close); unmatched bets are reported, not counted.
    """
    return _asdict(clv_report(settings.predictions_log, settings.line_history_log))


# ============================================================================
# MULTI-VERTICAL ROUTES (Generic Prediction Platform)
# ============================================================================

@app.get("/verticals")
def list_verticals() -> dict:
    """List all available prediction verticals."""
    return {
        "verticals": [
            {
                "id": "mlb",
                "name": "MLB Props",
                "description": "Pitcher strikeout predictions vs DraftKings/FanDuel",
                "path": "/verticals/mlb",
                "markets": ["DraftKings", "FanDuel"],
            },
            {
                "id": "ai-releases",
                "name": "AI Releases",
                "description": "Claude, GPT, xAI release date predictions (Polymarket)",
                "path": "/verticals/ai-releases",
                "markets": ["Polymarket"],
            },
            {
                "id": "economics",
                "name": "Fed & Economics",
                "description": "CPI, interest rates, unemployment predictions (Polymarket, Kalshi)",
                "path": "/verticals/economics",
                "markets": ["Polymarket", "Kalshi"],
            },
            {
                "id": "earnings",
                "name": "Company Earnings",
                "description": "Beat/miss probability predictions (options + consensus)",
                "path": "/verticals/earnings",
                "markets": ["Options Market"],
            },
            {
                "id": "crypto",
                "name": "Crypto Events",
                "description": "Bitcoin price targets, ETF approvals, milestones (Polymarket)",
                "path": "/verticals/crypto",
                "markets": ["Polymarket"],
            },
        ]
    }


@app.get("/verticals/mlb")
async def vertical_mlb(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    min_edge: float | None = Query(0.05, description="Min edge to display"),
) -> dict:
    """MLB strikeout vertical - returns today's best edges."""
    # Call slate_v2 with explicit plain values: invoked directly (not via FastAPI
    # dependency injection), so the remaining params must not keep their Query() defaults.
    return await slate_v2(
        date=date,
        min_edge=min_edge,
        max_bets=4,
        max_per_game=1,
        select_min_edge=0.05,
        select_max_edge=0.20,
        min_completeness=0.5,
        kelly_fraction=None,
        sharp_check=False,
    )


@app.get("/verticals/ai-releases")
async def vertical_ai_releases(
    market: str = Query("polymarket", description="Market source (polymarket)"),
) -> dict:
    """AI release predictions (Claude, GPT, xAI, Gemini) from LIVE Polymarket markets."""
    payload = await pmkt.vertical_payload(
        "ai-releases",
        queries=[
            "AI model", "GPT", "OpenAI", "Anthropic Claude", "Google Gemini",
            "xAI Grok", "best AI model", "AGI",
        ],
        now=_time.time(),
        exclude=["before gta", "jesus", "largest company"],
        min_liquidity=500.0,
    )
    payload["timestamp"] = _today()
    return payload


@app.get("/verticals/economics")
async def vertical_economics(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
) -> dict:
    """Fed & Economics predictions (CPI, rates, GDP, recession) from LIVE Polymarket markets."""
    now = _time.time()
    macro = await sig.get_macro(now)

    def econ_signal(norm: dict):
        return sig.econ_signal(norm["question"], norm["yes_price"], macro)

    payload = await pmkt.vertical_payload(
        "economics",
        queries=[
            "Fed interest rate", "rate cut", "CPI inflation", "recession",
            "GDP growth", "unemployment", "federal funds rate", "Jerome Powell",
        ],
        now=now,
        exclude=["anthropic", "openai"],  # keep AI-stake markets out of econ
        min_liquidity=500.0,
        signal_fn=econ_signal,
        model_tag=f"economics-v2 (Polymarket + macro anchor, {macro.get('source','')})",
    )
    payload["timestamp"] = _today()
    payload["date"] = date or _today()
    payload["macro"] = macro
    return payload


@app.get("/verticals/earnings")
async def vertical_earnings(
    sector: str = Query("tech", description="Sector (tech, finance, energy)"),
) -> dict:
    """Company earnings / revenue beat-miss predictions from LIVE Polymarket markets."""
    now = _time.time()
    caps = await sig.get_market_caps(now)

    def earn_signal(norm: dict):
        return sig.earnings_signal(norm["question"], norm["yes_price"], caps)

    payload = await pmkt.vertical_payload(
        "earnings",
        queries=[
            "earnings", "quarterly revenue", "Nvidia", "Tesla", "Apple",
            "Microsoft", "Amazon", "largest company market cap", "company revenue",
        ],
        now=now,
        exclude=["wimbledon", "tennis", "win on", " vs ", " beat the ",
                 "election", "best ai model", "before gta"],
        min_liquidity=200.0,
        signal_fn=earn_signal,
        model_tag="earnings-v2 (Polymarket + live market caps via Yahoo)",
    )
    payload["timestamp"] = _today()
    payload["sector"] = sector
    return payload


@app.get("/verticals/crypto")
async def vertical_crypto(
    market: str = Query("polymarket", description="Market source (polymarket)"),
    event: str | None = Query(None, description="(legacy) specific event key"),
) -> dict:
    """Crypto predictions (Bitcoin/ETH/SOL price targets, ETFs) from LIVE Polymarket markets."""
    payload = await pmkt.vertical_payload(
        "crypto",
        queries=[
            "Bitcoin price", "Ethereum", "Solana", "crypto", "XRP Ripple",
            "Dogecoin", "Ethereum ETF",
        ],
        now=_time.time(),
        exclude=["up or down", "satoshi"],  # drop 5-minute noise + novelty
        min_liquidity=2000.0,
    )
    payload["timestamp"] = _today()
    return payload


@app.get("/verticals/crypto/event/{event_id}")
async def crypto_event_detail(
    event_id: str = PathParam(..., description="Event ID (bitcoin_150k_dec, ethereum_etf, solana_300)"),
) -> dict:
    """Detailed analysis for a specific crypto event.

    Includes current price data, on-chain metrics, options market conditions,
    news sentiment, and model prediction with feature importance.
    """
    try:
        predictor = CryptoEventPredictor()
        result = await predictor.predict_event(event_id)

        return {
            "event": result.event,
            "timestamp": result.timestamp,
            "data_quality": result.data_quality,
            "predictions": [
                {
                    "event": pred.event,
                    "predicted_probability": pred.predicted_probability,
                    "confidence": pred.confidence,
                    "polymarket_reference": pred.polymarket_probability,
                    "edge": pred.edge,
                    "key_factors": pred.key_factors,
                    "updated_at": pred.updated_at,
                }
                for pred in result.predictions
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)}")
