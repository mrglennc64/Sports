"""Build a parlay from per-leg ensemble projections.

Thin orchestration: for each requested leg (pitcher, line, side, book odds) it
asks the ensemble pipeline for that pitcher's projection, pulls the model
probability for the chosen side, then hands the assembled legs to the pure
:func:`app.model.parlay.evaluate_parlay`. The projections are the foundation;
this module just composes them — it adds no new modelling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

from app.config import Settings
from app.config import settings as default_settings
from app.data.client import StatsApiClient
from app.ensemble_pipeline import build_slate_ensemble, predict_pitcher_ensemble
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
    max_legs: int = 3,
    block_same_game: bool = True,
    log: bool = False,
    settings: Settings = default_settings,
) -> dict:
    """Project every leg, combine into a parlay, and return a JSON-able result.

    Each leg's model probability comes from the ensemble projection for that
    pitcher on its date; the book odds are supplied by the caller. Raises
    ``LookupError`` (propagated from the projection) if a pitcher isn't starting,
    and ``ValueError`` for a bad side, no legs, or a violated parlay guard.

    Guards (enforced as HARD RULES here, unlike the warn-only pure engine):
    ``max_legs`` caps the parlay (default 3 — 2–3 sharp legs is the variance/vig
    sweet spot) and ``block_same_game`` rejects correlated same-game legs whose
    product EV would be a fiction (default True).

    ``log=True`` appends each leg to the predictions log (as a non-flagged row)
    so the leg's probability is later settled and scored by /calibration — wiring
    parlays into the same honesty tracking as the daily slate.
    """
    if not specs:
        raise ValueError("a parlay needs at least one leg")
    if max_legs is not None and len(specs) > max_legs:
        # Fail fast before spending projection calls on a parlay we'll reject.
        raise ValueError(
            f"parlay has {len(specs)} legs but max_legs={max_legs} — long parlays "
            "stack variance and compounded vig; keep it to 2–3 sharp legs"
        )

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
            max_legs=max_legs,
            block_same_game=block_same_game,
        )
        if log and log_rows:
            log_predictions(log_rows, settings.predictions_log)

        result = asdict(evaluation)
        result["legs_logged"] = len(log_rows) if log else 0
        return result
    finally:
        if owns:
            await client.aclose()


def _card_leg(row: dict) -> ParlayLeg | None:
    """Turn a selected slate-card row into a parlay leg, or None if unusable.

    The card row already carries the chosen side, that side's book odds, the
    model probability (which ALREADY reflects the configured ``prob_shrinkage`` —
    it comes through the same ensemble bridge as the slate), and ``game_pk`` for
    the independence check. We only build legs from rows the slate already flagged
    as +EV, confident bets, so the suggester never invents a play.
    """
    side = row.get("side")
    if side not in ("over", "under"):
        return None
    prob = row.get("model_prob")
    odds = row.get("over_odds") if side == "over" else row.get("under_odds")
    if prob is None or odds is None or not 0.0 < prob < 1.0:
        return None
    return ParlayLeg(
        label=f"{row.get('pitcher', '?')} {side.capitalize()} {row.get('line')} Ks",
        model_prob=prob,
        american_odds=odds,
        game_id=row.get("game_pk"),
    )


async def suggest_parlays(
    date: str,
    *,
    client: StatsApiClient | None = None,
    settings: Settings = default_settings,
    max_legs: int = 3,
    max_suggestions: int = 5,
    kelly_fraction: float | None = None,
    kelly_cap: float | None = None,
) -> dict:
    """Auto-suggest +EV parlays from today's bet card — independence guaranteed.

    Builds the daily slate card (already diversified to one bet per game, so every
    card leg is in a different game and the legs are independent by construction),
    then enumerates every 2..``max_legs`` combination, evaluates each as a parlay,
    and returns the **positive-EV** ones ranked by EV per unit. Because the card's
    ``model_prob`` already includes the configured shrinkage, the reported EV is
    the honest, production-consistent number — not a payout multiple dressed up as
    an edge.

    This never parlays correlated legs (the card is one-per-game) and is capped at
    ``max_legs`` — the same hard rules ``build_parlay`` enforces, here by design.
    """
    owns = client is None
    client = client or StatsApiClient()
    try:
        slate = await build_slate_ensemble(date, client=client, settings=settings)
        card = slate.get("card", [])
        legs = [leg for leg in (_card_leg(r) for r in card) if leg is not None]

        kf = kelly_fraction if kelly_fraction is not None else settings.kelly_fraction
        kc = kelly_cap if kelly_cap is not None else settings.kelly_cap

        suggestions: list[dict] = []
        for size in range(2, min(max_legs, len(legs)) + 1):
            for combo in combinations(legs, size):
                ev = evaluate_parlay(
                    list(combo),
                    kelly_fraction=kf,
                    kelly_cap=kc,
                    max_legs=max_legs,
                    block_same_game=True,
                )
                if not ev.positive_ev:
                    continue
                row = asdict(ev)
                row["legs"] = [
                    {
                        "label": leg.label,
                        "model_prob": round(leg.model_prob, 4),
                        "american_odds": leg.american_odds,
                        "game_id": leg.game_id,
                    }
                    for leg in combo
                ]
                suggestions.append(row)

        suggestions.sort(key=lambda r: r["ev_per_unit"], reverse=True)
        suggestions = suggestions[:max_suggestions]

        return {
            "date": date,
            "card_size": len(card),
            "eligible_legs": len(legs),
            "max_legs": max_legs,
            "n_suggestions": len(suggestions),
            "suggestions": suggestions,
            "note": (
                "Built only from today's +EV bet-card legs (one per game, so "
                "independent). Probabilities include the configured shrinkage; "
                "EV is the honest production number, not a payout multiple."
            ),
        }
    finally:
        if owns:
            await client.aclose()
