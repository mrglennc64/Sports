"""Parlay evaluator — a layer ON TOP of the per-leg strikeout projections.

A parlay wins only if every leg hits. If the legs are INDEPENDENT, the parlay's
true win probability is the product of the per-leg model probabilities, and the
book's parlay payout is the product of the per-leg decimal odds. We compare the
two to get expected value.

This module is pure: it takes each leg's already-computed model probability
(from :mod:`app.model.projection` via the ensemble bridge) plus the book odds,
and combines them. It does NOT re-derive projections — it consumes them.

The independence caveat is the whole ballgame:
  * Different games  -> roughly independent; the product is a fair estimate.
  * Same game / same pitcher -> CORRELATED; multiplying overstates the true
    probability (a pitcher going Over Ks and his team's total are linked). We
    detect shared ``game_id`` legs and attach a warning instead of pretending.

Vig compounds across legs, so multi-leg parlays carry a large built-in house
edge — most parlays are -EV even when each leg is fairly priced. We report EV
honestly rather than dressing up the payout multiple as an edge.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import prod

from app.model.edge import american_to_decimal, decimal_to_american, safe_kelly


@dataclass
class ParlayLeg:
    """One leg: a model probability (from the projection) + the book's price."""

    label: str
    model_prob: float  # P(this leg hits), from the ensemble (0..1)
    american_odds: float  # book price for this leg's chosen side
    game_id: str | int | None = None  # for the same-game correlation guard


@dataclass
class ParlayEvaluation:
    n_legs: int
    model_prob: float  # product of leg probs (independence-assumed)
    book_decimal: float  # product of leg decimal odds (the payout multiple)
    implied_prob: float  # 1 / book_decimal (still vigged)
    fair_decimal: float  # 1 / model_prob (zero-vig fair price)
    ev_per_unit: float  # model_prob * book_decimal - 1  (>0 means +EV)
    kelly: float  # fractional, capped stake for the parlay as one bet
    positive_ev: bool
    independent: bool  # False if any two legs share a game_id
    warnings: list[str] = field(default_factory=list)
    legs: list[ParlayLeg] = field(default_factory=list)


def _correlation_warnings(legs: list[ParlayLeg]) -> tuple[list[str], bool]:
    """Warn about legs sharing a game (independence violated). Returns (warns, independent)."""
    warns: list[str] = []
    by_game: dict[str | int, list[str]] = defaultdict(list)
    for leg in legs:
        if leg.game_id is not None:
            by_game[leg.game_id].append(leg.label)
    independent = True
    for game_id, labels in by_game.items():
        if len(labels) > 1:
            independent = False
            warns.append(
                f"Legs {labels} are in the same game (game_id={game_id}); they are "
                "correlated, so the combined probability is OVERSTATED — treat this "
                "parlay's EV as optimistic."
            )
    return warns, independent


def evaluate_parlay(
    legs: list[ParlayLeg],
    *,
    kelly_fraction: float = 0.25,
    kelly_cap: float = 0.05,
) -> ParlayEvaluation:
    """Combine independent leg projections into a parlay EV + stake.

    Raises ``ValueError`` on an empty leg list or an out-of-range probability.
    """
    if not legs:
        raise ValueError("a parlay needs at least one leg")
    for leg in legs:
        if not 0.0 < leg.model_prob < 1.0:
            raise ValueError(f"leg {leg.label!r} has invalid model_prob {leg.model_prob}")

    model_prob = prod(leg.model_prob for leg in legs)
    book_decimal = prod(american_to_decimal(leg.american_odds) for leg in legs)
    ev_per_unit = model_prob * book_decimal - 1.0

    warns, independent = _correlation_warnings(legs)
    if len(legs) >= 4:
        warns.append(
            f"{len(legs)}-leg parlay: high variance and compounded vig — most long "
            "parlays are -EV even with fair legs."
        )

    # Kelly for the parlay treated as a single bet at the combined price.
    kelly = safe_kelly(
        model_prob, decimal_to_american(book_decimal), kelly_fraction, kelly_cap
    )

    return ParlayEvaluation(
        n_legs=len(legs),
        model_prob=model_prob,
        book_decimal=book_decimal,
        implied_prob=1.0 / book_decimal,
        fair_decimal=1.0 / model_prob,
        ev_per_unit=ev_per_unit,
        kelly=kelly,
        positive_ev=ev_per_unit > 0,
        independent=independent,
        warnings=warns,
        legs=legs,
    )
