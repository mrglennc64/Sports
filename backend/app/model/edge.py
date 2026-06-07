"""Odds conversion, vig removal, edge, and Kelly staking.

The single most important correction over the source blueprints: book odds embed
the bookmaker's margin ("vig"). Computing implied probability as ``1/decimal`` and
comparing it to the model would credit us with edge that is really just the vig.
We instead DE-VIG the two-sided (over/under) market before measuring edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# --- odds conversions ---------------------------------------------------------

def american_to_decimal(american: float) -> float:
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_american(decimal: float) -> float:
    if decimal <= 1.0:
        raise ValueError("decimal odds must be > 1.0")
    if decimal >= 2.0:
        return (decimal - 1.0) * 100.0
    return -100.0 / (decimal - 1.0)


def implied_prob(american: float) -> float:
    """Raw implied probability from American odds (still contains vig)."""
    return 1.0 / american_to_decimal(american)


def prob_to_american(prob: float) -> float:
    """Fair American odds for a given true probability."""
    if not 0.0 < prob < 1.0:
        raise ValueError("prob must be in (0, 1)")
    return decimal_to_american(1.0 / prob)


# --- de-vig -------------------------------------------------------------------

def _devig_proportional(raw: list[float]) -> list[float]:
    """Multiplicative de-vig: scale raw implied probs to sum to 1."""
    total = sum(raw)
    if total <= 0:
        raise ValueError("invalid odds")
    return [r / total for r in raw]


def _devig_shin(raw: list[float], max_iter: int = 100) -> list[float]:
    """Shin's method de-vig (Shin 1992/1993).

    Models the overround as arising from a fraction ``z`` of insider money and
    recovers truer probabilities, correcting the favourite-longshot bias that the
    plain proportional method leaves in. For a symmetric market it returns the same
    result as proportional; the two diverge as the market gets lopsided.

    Technique adapted from mberk/shin and gotoConversion/goto_conversion (GitHub
    topic: betting). Pure Python, no dependency added.
    """
    booksum = sum(raw)
    if booksum <= 0:
        raise ValueError("invalid odds")

    def prob_sum(z: float) -> float:
        return sum(
            (math.sqrt(z * z + 4 * (1 - z) * q * q / booksum) - z) / (2 * (1 - z))
            for q in raw
        )

    # prob_sum is decreasing in z; prob_sum(0) = sqrt(booksum) >= 1. Bisect for == 1.
    lo, hi = 0.0, 0.5
    z = 0.0
    for _ in range(max_iter):
        z = (lo + hi) / 2
        if prob_sum(z) > 1.0:
            lo = z
        else:
            hi = z
    return [
        (math.sqrt(z * z + 4 * (1 - z) * q * q / booksum) - z) / (2 * (1 - z))
        for q in raw
    ]


def devig_two_way(
    odds_a: float, odds_b: float, method: str = "proportional"
) -> tuple[float, float]:
    """Remove vig from a two-outcome market (e.g. over/under).

    ``method`` is "proportional" (default, multiplicative normalisation) or "shin".
    Returns the de-vigged ``(p_a, p_b)`` which sum to 1.
    """
    raw = [implied_prob(odds_a), implied_prob(odds_b)]
    if method == "shin":
        p = _devig_shin(raw)
    elif method == "proportional":
        p = _devig_proportional(raw)
    else:
        raise ValueError(f"unknown devig method: {method!r}")
    return p[0], p[1]


# --- edge + staking -----------------------------------------------------------

def edge(model_prob: float, fair_implied_prob: float) -> float:
    """Model probability minus the de-vigged market probability for the SAME side."""
    return model_prob - fair_implied_prob


def kelly_fraction(prob: float, american_odds: float) -> float:
    """Full-Kelly fraction of bankroll. f* = (b*p - q) / b.

    b = decimal odds - 1, p = model win prob, q = 1 - p. Negative -> no bet.
    """
    b = american_to_decimal(american_odds) - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - prob
    return (b * prob - q) / b


def safe_kelly(prob: float, american_odds: float, fraction: float, cap: float) -> float:
    """Fractional Kelly, floored at 0 and capped at ``cap`` of bankroll."""
    full = kelly_fraction(prob, american_odds)
    if full <= 0:
        return 0.0
    return min(full * fraction, cap)


@dataclass
class SideEval:
    """Evaluation of one side (over or under) of a strikeout prop."""

    side: str            # "over" | "under"
    model_prob: float    # Poisson probability for this side
    book_odds: float     # American odds offered for this side
    fair_prob: float     # de-vigged market probability for this side
    edge: float          # model_prob - fair_prob
    kelly: float         # safe (fractional, capped) stake fraction


def evaluate_prop(
    line: float,
    over_odds: float,
    under_odds: float,
    model_prob_over: float,
    model_prob_under: float,
    kelly_fraction_: float,
    kelly_cap: float,
    devig_method: str = "proportional",
) -> SideEval:
    """Evaluate both sides of a prop and return the better (higher-edge) side."""
    fair_over, fair_under = devig_two_way(over_odds, under_odds, method=devig_method)

    over = SideEval(
        side="over",
        model_prob=model_prob_over,
        book_odds=over_odds,
        fair_prob=fair_over,
        edge=edge(model_prob_over, fair_over),
        kelly=safe_kelly(model_prob_over, over_odds, kelly_fraction_, kelly_cap),
    )
    under = SideEval(
        side="under",
        model_prob=model_prob_under,
        book_odds=under_odds,
        fair_prob=fair_under,
        edge=edge(model_prob_under, fair_under),
        kelly=safe_kelly(model_prob_under, under_odds, kelly_fraction_, kelly_cap),
    )
    return over if over.edge >= under.edge else under
