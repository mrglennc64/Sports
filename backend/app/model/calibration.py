"""Probability calibration — shrink overconfident model probabilities.

The first backtest showed the model's edges are overconfident above ~5%: it
claimed 60-68% win probability and actually won 36-41%. Shrinking each
probability toward 0.5 (a fair two-way market's break-even) pulls those inflated
edges back toward the market, which is the right prior when a model disagrees
with an efficient line.

The shrink factor ``k`` in [0, 1]:
  * k = 1.0  -> unchanged (full trust in the model)
  * k = 0.5  -> halve the model's deviation from a coin flip
  * k = 0.0  -> collapse to 0.5 (no edges, no bets)

This is regularization toward the market, deliberately NOT a value fit to the
(tiny) backtest sample — fitting k to ~50 games would just overfit noise.
"""

from __future__ import annotations


def shrink_to_even(prob: float, k: float) -> float:
    """Pull ``prob`` toward 0.5 by factor ``k``. Clamped to [0, 1]."""
    return min(1.0, max(0.0, 0.5 + k * (prob - 0.5)))
