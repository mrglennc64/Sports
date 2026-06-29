"""Tests for correlated-exposure capping (app.model.risk)."""

from __future__ import annotations

import pytest

from app.model.risk import cap_correlated


def test_group_under_cap_is_untouched():
    legs = cap_correlated(["sale", "bradish"], [0.04, 0.03], group_cap=0.08)
    assert [l.kelly_capped for l in legs] == [0.04, 0.03]
    assert all(not l.capped for l in legs)


def test_over_staked_group_is_scaled_to_the_cap():
    # Same pitcher quoted three times: 0.05 + 0.05 + 0.05 = 0.15 on ONE outcome.
    legs = cap_correlated(["sale", "sale", "sale"], [0.05, 0.05, 0.05], group_cap=0.08)
    total = sum(l.kelly_capped for l in legs)
    assert total == pytest.approx(0.08)         # group lands exactly on the cap
    assert all(l.capped for l in legs)
    # Relative sizes preserved (all equal here).
    assert legs[0].kelly_capped == pytest.approx(legs[1].kelly_capped)


def test_scaling_preserves_relative_leg_sizes():
    legs = cap_correlated(["p", "p"], [0.06, 0.02], group_cap=0.04)
    a, b = legs[0].kelly_capped, legs[1].kelly_capped
    assert a + b == pytest.approx(0.04)
    assert a / b == pytest.approx(0.06 / 0.02)  # 3:1 ratio kept


def test_groups_are_independent():
    legs = cap_correlated(
        ["sale", "sale", "bradish"], [0.05, 0.05, 0.07], group_cap=0.08
    )
    sale = [l for l in legs if l.key == "sale"]
    bradish = [l for l in legs if l.key == "bradish"][0]
    assert sum(l.kelly_capped for l in sale) == pytest.approx(0.08)  # capped
    assert bradish.kelly_capped == pytest.approx(0.07)               # untouched
    assert not bradish.capped


def test_never_increases_a_leg():
    legs = cap_correlated(["a", "b"], [0.01, 0.02], group_cap=0.10)
    assert legs[0].kelly_capped <= 0.01
    assert legs[1].kelly_capped <= 0.02


def test_negative_legs_contribute_nothing_and_clamp_to_zero():
    legs = cap_correlated(["p", "p"], [-0.03, 0.05], group_cap=0.08)
    # The no-bet (-0.03) leg adds nothing to the group total, so 0.05 < cap stays.
    assert legs[1].kelly_capped == pytest.approx(0.05)
    assert legs[0].kelly_capped == 0.0


def test_nonpositive_cap_zeroes_everything():
    legs = cap_correlated(["a", "b"], [0.05, 0.05], group_cap=0.0)
    assert all(l.kelly_capped == 0.0 for l in legs)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        cap_correlated(["a"], [0.05, 0.05], group_cap=0.08)
