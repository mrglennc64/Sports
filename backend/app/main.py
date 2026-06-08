"""FastAPI service exposing the strikeout-edge model.

Routes:
  GET /health      - liveness + active odds provider
  GET /predict     - single-pitcher calc, season-K/9 multiplier model (v1)
  GET /slate       - ranked +EV edges for a date, multiplier model (v1)
  GET /v2/predict  - single-pitcher calc, v2 ensemble + bridge (unified model)
  GET /v2/slate    - ranked +EV edges for a date, v2 ensemble + bridge
  GET /v2/arb      - cross-book strikeout arbitrage scan
  GET /backtest    - settle logged predictions vs actual results
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date as date_cls

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from dataclasses import asdict as _asdict

from app.arb_pipeline import scan_arbitrage
from app.backtest.metrics import summarize
from app.backtest.settle import settle_predictions
from app.config import settings
from app.ensemble_pipeline import build_slate_ensemble, predict_pitcher_ensemble
from app.log.predictions import log_predictions
from app.pipeline import build_slate, predict_pitcher

app = FastAPI(title="MLB Strikeout Edge Platform", version="1.0.0")

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
    allow_methods=["GET"],
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
) -> dict:
    """Ranked +EV pitcher-strikeout edges for a date via the v2 ensemble bridge."""
    result = await build_slate_ensemble(date or _today())
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


@app.get("/backtest")
def backtest() -> dict:
    """Settle logged predictions vs actual results -> hit rate, ROI, MAE."""
    settled = settle_predictions(settings.predictions_log)
    return _asdict(summarize(settled))
