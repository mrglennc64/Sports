"""Hedge an EXISTING position — the CLV-lock calculator.

Distinct from :mod:`app.model.arb`, which finds a *simultaneous* two-book arb
(both legs placed now at an optimal split). Here you ALREADY placed an early bet
at a price you liked (positive CLV), the line then moved, and the opposite side
is now available at a price that may let you lock a guaranteed result by betting
the other way.

You took ``initial_stake`` on one side at ``initial_odds``. Betting the opposite
side now at ``hedge_odds`` for a stake that equalises the payout on both outcomes
locks the same net result whether your original side wins or loses::

    hedge_stake = (initial_stake * dec_initial) / dec_hedge

A guaranteed profit exists only when the two prices form an arb across time:
``1/dec_initial + 1/dec_hedge < 1``. Otherwise the "hedge" merely caps a loss —
which the result still reports honestly, because a smaller locked loss is often
the right risk decision even when it isn't free money. Pure math, no I/O; reuses
the odds conversion in :mod:`app.model.edge`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.model.edge import american_to_decimal


@dataclass
class HedgeResult:
    initial_stake: float
    initial_odds: float
    hedge_odds: float
    hedge_stake: float          # bet this on the opposite side to equalise payout
    total_outlay: float         # initial_stake + hedge_stake (capital at risk)
    locked_return: float        # gross return on either outcome (equal by construction)
    locked_profit: float        # locked_return - total_outlay (negative = capped loss)
    roi_pct: float              # locked_profit / total_outlay * 100
    risk_free: bool             # True only if locked_profit > 0 (a real arb across time)


def hedge_existing_position(
    initial_stake: float,
    initial_odds: float,
    hedge_odds: float,
) -> HedgeResult:
    """Stake on the opposite side that equalises payout across both outcomes.

    ``initial_odds``/``hedge_odds`` are American (e.g. ``+115``/``-105``). The
    equal-payout hedge locks the same net on either result; whether that net is a
    profit depends on the two prices (it's free money only if they form a
    cross-time arb). Raises ``ValueError`` on a non-positive stake.
    """
    if initial_stake <= 0:
        raise ValueError("initial_stake must be positive")

    dec_initial = american_to_decimal(initial_odds)
    dec_hedge = american_to_decimal(hedge_odds)

    locked_return = initial_stake * dec_initial          # match this on the hedge side
    hedge_stake = locked_return / dec_hedge
    total_outlay = initial_stake + hedge_stake
    locked_profit = locked_return - total_outlay
    roi_pct = (locked_profit / total_outlay * 100.0) if total_outlay else 0.0

    return HedgeResult(
        initial_stake=round(initial_stake, 2),
        initial_odds=initial_odds,
        hedge_odds=hedge_odds,
        hedge_stake=round(hedge_stake, 2),
        total_outlay=round(total_outlay, 2),
        locked_return=round(locked_return, 2),
        locked_profit=round(locked_profit, 2),
        roi_pct=round(roi_pct, 2),
        risk_free=locked_profit > 0,
    )
