"""FastAPI service exposing the strikeout-edge model.

Routes:
  GET /health   - liveness + active odds provider
  GET /predict  - single-pitcher manual calculation (optionally with book odds)
  GET /slate    - the product: ranked +EV pitcher-strikeout edges for a date
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date as date_cls

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from dataclasses import asdict as _asdict

from app.backtest.metrics import summarize
from app.backtest.settle import settle_predictions
from app.config import settings
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


@app.get("/backtest")
def backtest() -> dict:
    """Settle logged predictions vs actual results -> hit rate, ROI, MAE."""
    settled = settle_predictions(settings.predictions_log)
    return _asdict(summarize(settled))
