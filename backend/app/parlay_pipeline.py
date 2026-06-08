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
from app.model.parlay import ParlayLeg, evaluate_parlay


@dataclass
class LegSpec:
    """One requested parlay leg."""

    pitcher: str
    line: float
    side: str  # "over" | "under"
    odds: float  # book American odds for the chosen side
    date: str | None = None


async def build_parlay(
    specs: list[LegSpec],
    on_date: str,
    *,
    client: StatsApiClient | None = None,
    kelly_fraction: float | None = None,
    kelly_cap: float | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Project every leg, combine into a parlay, and return a JSON-able result.

    Each leg's model probability comes from the ensemble projection for that
    pitcher on its date; the book odds are supplied by the caller. Raises
    ``LookupError`` (propagated from the projection) if a pitcher isn't starting,
    and ``ValueError`` for a bad side or no legs.
    """
    if not specs:
        raise ValueError("a parlay needs at least one leg")

    owns = client is None
    client = client or StatsApiClient()
    try:
        legs: list[ParlayLeg] = []
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

        evaluation = evaluate_parlay(
            legs,
            kelly_fraction=kelly_fraction if kelly_fraction is not None else settings.kelly_fraction,
            kelly_cap=kelly_cap if kelly_cap is not None else settings.kelly_cap,
        )
        return asdict(evaluation)
    finally:
        if owns:
            await client.aclose()
