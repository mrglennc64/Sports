"""Capital control — a hard-cap bankroll model that sits ABOVE per-bet sizing.

Kelly answers "how much on THIS bet"; it cannot see the bankroll as a finite
runway and will happily ride a miscalibrated edge into ruin. This module is the
top-down guardrail the way a fund treats capital, not a gambler treats a roll:

  * lock a **reserve floor** that is never staked (the money that lets you continue
    after a bad cycle),
  * spread the remaining **working capital** over a fixed **investment cycle**
    (a number of days), and
  * hand back a **hard daily ceiling**.

Per-bet sizing (flat units or fractional-Kelly) then operates strictly *under*
that ceiling. Pure math, no I/O.

Honesty note: this controls the *rate of loss*, not the *sign* of EV. No staking
plan turns -EV bets into +EV ones — it only bounds how fast a losing edge can
draw the bankroll down. Proven per-leg edge (positive CLV) is still the only
thing that makes the whole exercise profitable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BankrollPlan:
    total_bankroll: float
    reserve_floor: float        # locked; never staked
    cycle_days: int             # the investment runway, in days
    working_capital: float      # total - reserve (the only money in play)
    daily_budget: float         # working / cycle -- the HARD daily ceiling
    reserve_intact: bool        # total_bankroll > reserve_floor
    verdict: str


def plan_bankroll(total_bankroll: float, reserve_floor: float, cycle_days: int) -> BankrollPlan:
    """Split a bankroll into a locked reserve + a daily working budget.

    ``daily_budget = (total_bankroll - reserve_floor) / cycle_days``. If the
    bankroll is at or below the reserve, working capital and the daily budget are
    0 (stop betting — protect the reserve). Raises ``ValueError`` on negative
    inputs or a non-positive cycle.
    """
    if total_bankroll < 0 or reserve_floor < 0:
        raise ValueError("bankroll and reserve must be non-negative")
    if cycle_days <= 0:
        raise ValueError("cycle_days must be positive")

    working = max(0.0, total_bankroll - reserve_floor)
    daily = working / cycle_days
    intact = total_bankroll > reserve_floor
    if not intact:
        verdict = (
            f"STOP: bankroll {total_bankroll:.2f} is at/below the reserve floor "
            f"{reserve_floor:.2f} — no working capital, daily budget is 0."
        )
    else:
        verdict = (
            f"{working:.2f} working capital over {cycle_days} days = "
            f"{daily:.2f}/day hard ceiling (reserve {reserve_floor:.2f} locked)."
        )
    return BankrollPlan(
        total_bankroll=round(total_bankroll, 2),
        reserve_floor=round(reserve_floor, 2),
        cycle_days=cycle_days,
        working_capital=round(working, 2),
        daily_budget=round(daily, 2),
        reserve_intact=intact,
        verdict=verdict,
    )


def remaining_runway(current_bankroll: float, reserve_floor: float, daily_budget: float) -> float:
    """Days of ``daily_budget`` left before the bankroll would hit the reserve.

    Recompute mid-cycle from the *current* bankroll: a winning run extends the
    runway, a losing run shortens it. Returns 0 once the reserve is reached.
    """
    if daily_budget <= 0:
        return 0.0
    return round(max(0.0, (current_bankroll - reserve_floor) / daily_budget), 2)


def cap_to_budget(proposed_stake: float, daily_budget: float, already_staked: float = 0.0) -> float:
    """Clamp a proposed stake to what's left of today's hard ceiling (never negative)."""
    remaining = max(0.0, daily_budget - already_staked)
    return round(max(0.0, min(proposed_stake, remaining)), 2)
