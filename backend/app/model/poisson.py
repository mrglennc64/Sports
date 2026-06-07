"""Poisson probability model for strikeout over/under lines.

Strikeouts in a start are count data, so a Poisson with mean ``lam`` (expected Ks)
is the natural baseline. Note: real strikeout counts are mildly UNDER-dispersed vs
Poisson, so probabilities near the line are slightly optimistic. This module is kept
deliberately small and isolated so a negative-binomial or ML-corrected distribution
can replace it later without touching the edge engine or API.
"""
from __future__ import annotations

import math

# Upper bound for summation. No starter realistically fans >25 in a game, and
# Poisson mass above this is negligible for any plausible lam.
_MAX_K = 25


def pmf(k: int, lam: float) -> float:
    """P(X = k) for X ~ Poisson(lam)."""
    if k < 0 or lam < 0:
        raise ValueError("k and lam must be non-negative")
    return (lam**k) * math.exp(-lam) / math.factorial(k)


def prob_over(lam: float, line: float) -> float:
    """P(strikeouts > line).

    Handles both half-lines (the common case, e.g. 6.5 -> P(K >= 7)) and integer
    lines (e.g. 7 -> P(K >= 8); the exact 7 is a push and excluded from "over").
    """
    threshold = math.floor(line) + 1  # smallest integer strictly greater than line
    return sum(pmf(k, lam) for k in range(threshold, _MAX_K + 1))


def prob_under(lam: float, line: float) -> float:
    """P(strikeouts < line) = P(K <= floor(line) when line is a half-line).

    For a half-line, over + under == 1. For an integer line the exact value is a
    push, so over + under < 1 by exactly P(X == line).
    """
    threshold = math.ceil(line) - 1  # largest integer strictly less than line
    if threshold < 0:
        return 0.0
    return sum(pmf(k, lam) for k in range(0, threshold + 1))
