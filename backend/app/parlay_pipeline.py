"""Build a parlay from per-leg ensemble projections.

Thin orchestration: for each requested leg (pitcher, line, side, book odds) it
asks the ensemble pipeline for that pitcher's projection, pulls the model
probability for the chosen side, then hands the assembled legs to the pure
:func:`app.model.parlay.evaluate_parlay`. The projections are the foundation;
this module just composes them — it adds no new modelling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.config import Settings
from app.config import settings as default_settings
from app.data.client import StatsApiClient
from app.ensemble_pipeline import predict_pitcher_ensemble
from app.log.predictions import log_predictions
from app.model.parlay import ParlayLeg, evaluate_parlay


@dataclass
class LegSpec:
    """One requested parlay leg."""

    pitcher: str
    line: float
    side: str  # "over" | "under"
    odds: float  # book American odds for the chosen side
    date: str | None = None


def _leg_log_row(proj: dict, spec: LegSpec, side: str, model_prob: float, on_date: str) -> dict:
    """A settle-able prediction row for one parlay leg.

    Mirrors the daily-slate log schema so the leg flows through the SAME
    settle -> /calibration pipeline as every other prediction. ``bet=False``
    keeps parlay legs out of /backtest's flagged-bet ROI (they aren't standalone
    +EV plays) while still feeding the probability-honesty sample, which is the
    point: more decided predictions sharpen calibration. Only the chosen side's
    odds are known, so the other side is left blank (settle reads the chosen one).
    """
    over_odds = spec.odds if side == "over" else ""
    under_odds = spec.odds if side == "under" else ""
    return {
        "date": proj.get("date") or spec.date or on_date,
        "pitcher": proj.get("pitcher", spec.pitcher),
        "pitcher_id": proj.get("pitcher_id", ""),
        "opponent": proj.get("opponent", ""),
        "venue": proj.get("venue", ""),
        "expected_ks": proj.get("expected_ks", ""),
        "line": spec.line,
        "side": side,
        "model_prob": round(model_prob, 4),
        "over_odds": over_odds,
        "under_odds": under_odds,
        "edge": 0.0,
        "bet": False,  # a parlay leg is not a flagged single bet
        "low_confidence": proj.get("low_confidence", False),
    }


async def build_parlay(
    specs: list[LegSpec],
    on_date: str,
    *,
    client: StatsApiClient | None = None,
    kelly_fraction: float | None = None,
    kelly_cap: float | None = None,
    log: bool = False,
    settings: Settings = default_settings,
) -> dict:
    """Project every leg, combine into a parlay, and return a JSON-able result.

    Each leg's model probability comes from the ensemble projection for that
    pitcher on its date; the book odds are supplied by the caller. Raises
    ``LookupError`` (propagated from the projection) if a pitcher isn't starting,
    and ``ValueError`` for a bad side or no legs.

    ``log=True`` appends each leg to the predictions log (as a non-flagged row)
    so the leg's probability is later settled and scored by /calibration — wiring
    parlays into the same honesty tracking as the daily slate.
    """
    if not specs:
        raise ValueError("a parlay needs at least one leg")

    owns = client is None
    client = client or StatsApiClient()
    try:
        legs: list[ParlayLeg] = []
        log_rows: list[dict] = []
        for spec in specs:
            side = spec.side.lower()
            if side not in ("over", "under"):
                raise ValueError(f"leg side must be 'over' or 'under', got {spec.side!r}")
            proj = await predict_pitcher_ensemble(
                spec.pitcher,
                line=spec.line,
                date=spec.date or on_date,
                client=client,
                settings=settings,
            )
            model_prob = proj["prob_over"] if side == "over" else proj["prob_under"]
            legs.append(
                ParlayLeg(
                    label=f"{proj['pitcher']} {side.capitalize()} {spec.line} Ks",
                    model_prob=model_prob,
                    american_odds=spec.odds,
                    game_id=proj.get("game_pk"),
                )
            )
            log_rows.append(_leg_log_row(proj, spec, side, model_prob, on_date))

        evaluation = evaluate_parlay(
            legs,
            kelly_fraction=kelly_fraction if kelly_fraction is not None else settings.kelly_fraction,
            kelly_cap=kelly_cap if kelly_cap is not None else settings.kelly_cap,
        )
        if log and log_rows:
            log_predictions(log_rows, settings.predictions_log)

        result = asdict(evaluation)
        result["legs_logged"] = len(log_rows) if log else 0
        return result
    finally:
        if owns:
            await client.aclose()
