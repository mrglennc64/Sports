"""Aggregate settled bets into the metrics that actually matter.

Model accuracy (MAE) is secondary; the headline numbers are ROI and hit-rate on the
bets the system would have placed. A profitable model beats the closing line over a
large sample — see clv.py for that piece.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.settle import SettledBet


@dataclass
class BacktestReport:
    n_predictions: int
    n_bets: int              # model-flagged bets only
    wins: int
    losses: int
    pushes: int
    hit_rate: float | None   # wins / decided bets
    roi: float | None        # profit units / bets staked
    total_profit_units: float
    mae: float | None        # |expected_ks - actual_ks| over all predictions


def _mae(settled: list[SettledBet]) -> float | None:
    if not settled:
        return None
    return sum(abs(s.expected_ks - s.actual_ks) for s in settled) / len(settled)


def summarize(settled: list[SettledBet]) -> BacktestReport:
    bets = [s for s in settled if s.flagged_bet]
    decided = [s for s in bets if s.result != "push"]
    wins = sum(1 for s in bets if s.result == "win")
    losses = sum(1 for s in bets if s.result == "loss")
    pushes = sum(1 for s in bets if s.result == "push")
    profit = sum(s.profit_units for s in bets)

    return BacktestReport(
        n_predictions=len(settled),
        n_bets=len(bets),
        wins=wins,
        losses=losses,
        pushes=pushes,
        hit_rate=(wins / len(decided)) if decided else None,
        roi=(profit / len(bets)) if bets else None,
        total_profit_units=round(profit, 3),
        mae=_mae(settled),
    )
