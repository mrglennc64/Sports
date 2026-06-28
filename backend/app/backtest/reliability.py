"""Probability reliability / calibration over settled predictions.

This answers a different question than its neighbours:

  * app/backtest/metrics.py   -> ROI & hit-rate on FLAGGED bets (did we profit?)
  * app/model/calibration.py  -> shrink probabilities toward 0.5 (a correction)
  * THIS module               -> are the probabilities themselves honest?

"When the model says 70%, does it happen ~70% of the time?" — scored across
EVERY decided prediction (not just +EV plays, not just flagged bets), so it's the
largest-sample, least-cherry-picked read on calibration. That breadth is the
point: a model can be unprofitable yet well-calibrated, or profitable on a lucky
handful yet badly calibrated. This separates the two.

Metrics:
  * Brier score      mean((p - y)^2)            — proper score, 0 = perfect.
  * Log loss         mean(-[y ln p + (1-y) ln(1-p)]) — punishes confident misses.
  * Reliability curve: bucket predictions by claimed probability; report the
    realized rate per bucket (the classic calibration plot, as a table).
  * ECE              sample-weighted mean |claimed - realized| across buckets.
  * reference_brier  p̄(1-p̄), the Brier of always guessing the base rate. The
    model only adds skill if its Brier is BELOW this.

Pushes (line landed exactly on the number) carry no win/loss signal and are
dropped. Predictions logged before model_prob existed are skipped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.backtest.settle import SettledBet

_EPS = 1e-9


@dataclass
class ReliabilityBin:
    lo: float            # bucket lower edge (inclusive)
    hi: float            # bucket upper edge (exclusive, except the top bin)
    n: int               # decided predictions in the bucket
    avg_predicted: float  # mean claimed probability in the bucket
    actual_rate: float   # realized win rate in the bucket
    gap: float           # actual_rate - avg_predicted (>0 = model underconfident)


@dataclass
class ReliabilityReport:
    n: int                          # decided predictions scored (push/None excluded)
    brier: float | None
    log_loss: float | None
    ece: float | None               # expected calibration error
    base_rate: float | None         # overall realized win rate
    avg_predicted: float | None     # overall mean claimed probability
    reference_brier: float | None   # p̄(1-p̄): Brier of always guessing base rate
    skill: bool | None              # brier < reference_brier (model beats base rate)
    bins: list[ReliabilityBin] = field(default_factory=list)
    verdict: str = ""


def _usable(settled: list[SettledBet]) -> list[tuple[float, int]]:
    """(model_prob, outcome) pairs for decided, probability-carrying predictions.

    outcome = 1 if the chosen side won, else 0. model_prob is the model's claimed
    probability of that chosen side, so a well-calibrated model's claimed prob
    should track the realized win rate.
    """
    pairs: list[tuple[float, int]] = []
    for s in settled:
        if s.result == "push" or s.model_prob is None:
            continue
        p = min(max(float(s.model_prob), 0.0), 1.0)
        pairs.append((p, 1 if s.result == "win" else 0))
    return pairs


def _bins(pairs: list[tuple[float, int]], n_bins: int) -> list[ReliabilityBin]:
    width = 1.0 / n_bins
    # Integer indexing avoids float-boundary ambiguity (e.g. 0.7 sitting just
    # below its decimal value in IEEE-754); the top edge folds into the last bin.
    groups: dict[int, list[tuple[float, int]]] = {}
    for p, y in pairs:
        idx = min(int(p * n_bins), n_bins - 1)
        groups.setdefault(idx, []).append((p, y))
    out: list[ReliabilityBin] = []
    for idx in sorted(groups):
        in_bin = groups[idx]
        m = len(in_bin)
        avg_p = sum(p for p, _ in in_bin) / m
        rate = sum(y for _, y in in_bin) / m
        out.append(ReliabilityBin(
            lo=round(idx * width, 4), hi=round((idx + 1) * width, 4), n=m,
            avg_predicted=round(avg_p, 4),
            actual_rate=round(rate, 4),
            gap=round(rate - avg_p, 4),
        ))
    return out


def _verdict(n: int, brier: float, reference: float, ece: float) -> str:
    if n < 100:
        return (f"n={n}: too small to conclude — this is variance, not a verdict. "
                "Revisit at a few hundred decided predictions.")
    skill = "beats" if brier < reference else "does NOT beat"
    cal = ("well calibrated" if ece < 0.05
           else "mildly miscalibrated" if ece < 0.10 else "poorly calibrated")
    return (f"n={n}: Brier {brier:.3f} {skill} the base-rate reference "
            f"{reference:.3f}; ECE {ece:.3f} -> {cal}.")


def reliability_report(
    settled: list[SettledBet], n_bins: int = 10
) -> ReliabilityReport:
    """Score the calibration of model probabilities against realized outcomes."""
    pairs = _usable(settled)
    n = len(pairs)
    if n == 0:
        return ReliabilityReport(
            n=0, brier=None, log_loss=None, ece=None, base_rate=None,
            avg_predicted=None, reference_brier=None, skill=None,
            verdict="no decided predictions with a logged probability yet",
        )

    brier = sum((p - y) ** 2 for p, y in pairs) / n
    log_loss = sum(
        -(y * math.log(min(max(p, _EPS), 1 - _EPS))
          + (1 - y) * math.log(min(max(1 - p, _EPS), 1 - _EPS)))
        for p, y in pairs
    ) / n
    base_rate = sum(y for _, y in pairs) / n
    avg_pred = sum(p for p, _ in pairs) / n
    reference_brier = base_rate * (1 - base_rate)

    bins = _bins(pairs, n_bins)
    ece = sum(b.n * abs(b.gap) for b in bins) / n if bins else 0.0

    return ReliabilityReport(
        n=n,
        brier=round(brier, 4),
        log_loss=round(log_loss, 4),
        ece=round(ece, 4),
        base_rate=round(base_rate, 4),
        avg_predicted=round(avg_pred, 4),
        reference_brier=round(reference_brier, 4),
        skill=brier < reference_brier,
        bins=bins,
        verdict=_verdict(n, brier, reference_brier, ece),
    )
