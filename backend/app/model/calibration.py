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


def best_shrink(graded: list[tuple[float, bool]]) -> tuple[float, float]:
    """Post-hoc optimal shrink factor on graded picks — MONITORING ONLY.

    ``graded``: (model probability of the leaned side, won?). Grid-searches k
    minimizing mean log-loss of the shrunk probabilities. Printed by the weekly
    report so the configured ``prob_shrinkage`` can be sanity-checked against
    evidence as the sample grows; deliberately NOT auto-applied (fitting k to a
    small sample would overfit noise — see module docstring).
    Returns (k, mean_log_loss_at_k).
    """
    import math

    best_k, best_ll = 1.0, float("inf")
    for step in range(21):
        k = step / 20
        total = 0.0
        for prob, won in graded:
            p = min(max(shrink_to_even(prob, k), 1e-9), 1 - 1e-9)
            total += -math.log(p if won else 1 - p)
        ll = total / len(graded)
        if ll < best_ll:
            best_k, best_ll = k, ll
    return best_k, best_ll
