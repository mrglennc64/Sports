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
from app.backtest.reliability import reliability_report
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
from app.parlay_pipeline import LegSpec, build_parlay
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


@app.get("/v2/slate")
async def slate_v2(
    date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    min_edge: float | None = Query(None, description="Filter: only rows with edge >= this"),
    max_bets: int = Query(4, ge=1, description="Card: max bets to flag"),
    max_per_game: int = Query(1, ge=1, description="Card: max bets from one game"),
    select_min_edge: float = Query(0.05, description="Card: min edge to be eligible"),
    select_max_edge: float = Query(0.20, description="Card: cap on edge (above = likely model error)"),
    min_completeness: float = Query(0.5, ge=0, le=1, description="Card: min input-completeness score"),
) -> dict:
    """Ranked +EV pitcher-strikeout edges for a date via the v2 ensemble bridge.

    Also returns a diversified ``card`` of the top ``max_bets`` plays for a small
    bankroll (edge band + per-game cap + input-completeness gate)."""
    result = await build_slate_ensemble(
        date or _today(),
        max_bets=max_bets,
        max_per_game=max_per_game,
        select_min_edge=select_min_edge,
        select_max_edge=select_max_edge,
        min_completeness=min_completeness,
    )
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
    log: bool = Field(
        False,
        description="Log each leg to the predictions log so it feeds /calibration",
    )


@app.post("/v2/parlay")
async def parlay(body: ParlayBody) -> dict:
    """Combine per-leg strikeout projections into a parlay EV + stake.

    Each leg's win probability comes from the v2 ensemble projection; you supply
    the book odds. Legs in the same game are flagged (correlated — the product
    overstates the true probability). Set ``log=true`` to record each leg (as a
    non-flagged prediction) so its probability is later scored by /calibration."""
    specs = [
        LegSpec(pitcher=l.pitcher, line=l.line, side=l.side, odds=l.odds, date=l.date)
        for l in body.legs
    ]
    try:
        return await build_parlay(specs, on_date=body.date or _today(), log=body.log)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    return await slate_v2(date=date, min_edge=min_edge)


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
