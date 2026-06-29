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

``round_to`` snaps the hedge stake to a whole-dollar increment ($5/$10) so the
bet blends in as a casual wager instead of an obviously-optimised number. Once
the stake is rounded the two outcomes no longer pay *exactly* the same, so the
result reports BOTH (``profit_if_initial`` / ``profit_if_hedge``) and treats the
worst of the two as the guaranteed floor — no pretending a rounded hedge is still
a perfect lock.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.model.edge import american_to_decimal


def _round_to(value: float, increment: float) -> float:
    """Round ``value`` to the nearest ``increment`` (half-up). ``<=0`` = no rounding."""
    if increment <= 0:
        return value
    return round(value / increment + 1e-9) * increment


@dataclass
class HedgeResult:
    initial_stake: float
    initial_odds: float
    hedge_odds: float
    hedge_stake: float          # bet this on the opposite side (rounded if round_to set)
    hedge_stake_exact: float    # the unrounded equalising stake (what perfect lock wants)
    round_to: float             # increment the stake was snapped to (0 = none)
    total_outlay: float         # initial_stake + hedge_stake (capital at risk)
    profit_if_initial: float    # net if the ORIGINAL side wins
    profit_if_hedge: float      # net if the HEDGE side wins
    locked_profit: float        # guaranteed floor = min(both outcomes); <0 = capped loss
    roi_pct: float              # locked_profit / total_outlay * 100
    risk_free: bool             # True only if the worst outcome is still a profit
    # legacy field kept for existing callers/tests: gross return if the original wins
    locked_return: float


def hedge_existing_position(
    initial_stake: float,
    initial_odds: float,
    hedge_odds: float,
    round_to: float = 0.0,
) -> HedgeResult:
    """Stake on the opposite side that equalises payout across both outcomes.

    ``initial_odds``/``hedge_odds`` are American (e.g. ``+115``/``-105``). The
    equalising hedge locks the same net on either result; whether that net is a
    profit depends on the two prices (it's free money only if they form a
    cross-time arb). ``round_to`` (e.g. ``5`` or ``10``) snaps the hedge stake to
    a whole-dollar increment for camouflage — the two outcomes then differ slightly
    and the worst is reported as the guaranteed floor. Raises ``ValueError`` on a
    non-positive stake.
    """
    if initial_stake <= 0:
        raise ValueError("initial_stake must be positive")

    dec_initial = american_to_decimal(initial_odds)
    dec_hedge = american_to_decimal(hedge_odds)

    return_if_initial = initial_stake * dec_initial    # gross if the original side wins
    hedge_stake_exact = return_if_initial / dec_hedge  # equalises the two outcomes
    hedge_stake = _round_to(hedge_stake_exact, round_to)

    total_outlay = initial_stake + hedge_stake
    return_if_hedge = hedge_stake * dec_hedge
    profit_if_initial = return_if_initial - total_outlay
    profit_if_hedge = return_if_hedge - total_outlay
    locked_profit = min(profit_if_initial, profit_if_hedge)
    roi_pct = (locked_profit / total_outlay * 100.0) if total_outlay else 0.0

    return HedgeResult(
        initial_stake=round(initial_stake, 2),
        initial_odds=initial_odds,
        hedge_odds=hedge_odds,
        hedge_stake=round(hedge_stake, 2),
        hedge_stake_exact=round(hedge_stake_exact, 2),
        round_to=round_to,
        total_outlay=round(total_outlay, 2),
        profit_if_initial=round(profit_if_initial, 2),
        profit_if_hedge=round(profit_if_hedge, 2),
        locked_profit=round(locked_profit, 2),
        roi_pct=round(roi_pct, 2),
        risk_free=locked_profit > 0,
        locked_return=round(return_if_initial, 2),
    )
