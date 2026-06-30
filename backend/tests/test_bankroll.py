"""Tests for the capital-control bankroll model (app.model.bankroll)."""
from __future__ import annotations

import pytest

from app.model.bankroll import cap_to_budget, plan_bankroll, remaining_runway


def test_plan_bankroll_example():
    # The worked example: $700 bankroll, $200 reserve, 30-day cycle.
    p = plan_bankroll(700, 200, 30)
    assert p.working_capital == 500.0
    assert p.daily_budget == pytest.approx(16.67, abs=0.01)
    assert p.reserve_intact is True
    assert "hard ceiling" in p.verdict


def test_reserve_breach_zeroes_the_budget():
    p = plan_bankroll(150, 200, 30)  # below the reserve floor
    assert p.working_capital == 0.0
    assert p.daily_budget == 0.0
    assert p.reserve_intact is False
    assert p.verdict.startswith("STOP")


def test_plan_bankroll_validates_inputs():
    with pytest.raises(ValueError):
        plan_bankroll(700, 200, 0)        # non-positive cycle
    with pytest.raises(ValueError):
        plan_bankroll(-1, 200, 30)        # negative bankroll
    with pytest.raises(ValueError):
        plan_bankroll(700, -1, 30)        # negative reserve


def test_remaining_runway_extends_and_shrinks():
    # daily budget 16.67; from 700 with 200 reserve -> 500/16.67 ~= 30 days.
    assert remaining_runway(700, 200, 16.67) == pytest.approx(30.0, abs=0.1)
    # a winning run to 900 extends the runway past the original cycle.
    assert remaining_runway(900, 200, 16.67) > 30
    # at/under the reserve, runway is 0.
    assert remaining_runway(200, 200, 16.67) == 0.0
    assert remaining_runway(150, 200, 16.67) == 0.0


def test_cap_to_budget_clamps():
    assert cap_to_budget(10, 16.5, already_staked=0) == 10.0
    assert cap_to_budget(10, 16.5, already_staked=12) == 4.5   # only 4.5 left
    assert cap_to_budget(10, 16.5, already_staked=16.5) == 0.0  # fully spent
    assert cap_to_budget(-5, 16.5) == 0.0                      # never negative
