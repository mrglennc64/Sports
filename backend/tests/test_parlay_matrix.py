"""Tests for the daily parlay matrix (app.parlay_matrix.build_matrix_from_legs)."""
from __future__ import annotations

from app.model.bankroll import plan_bankroll
from app.model.parlay import ParlayLeg
from app.parlay_matrix import (
    MAX_MATRIX_LEGS,
    Tier,
    build_matrix_from_legs,
)


def _legs(n, prob, odds):
    # n independent legs (distinct game_ids), same prob/odds for simple math.
    return [ParlayLeg(label=f"L{i} O Ks", model_prob=prob, american_odds=odds, game_id=i)
            for i in range(n)]


def test_positive_ev_legs_build_all_tiers():
    # 0.60 @ -110 is a +EV leg; products stay +EV, so every tier should build.
    legs = _legs(6, 0.60, -110)
    plan = plan_bankroll(700, 200, 30)  # $16.67/day
    m = build_matrix_from_legs(legs, plan)
    by = {t["name"]: t for t in m["tiers"]}
    assert all(by[name]["built"] for name in ("small", "medium", "large"))
    # stakes respect the 50/30/20 split of the daily budget and sum to it.
    assert by["small"]["stake"] > by["medium"]["stake"] > by["large"]["stake"]
    assert m["total_staked"] <= plan.daily_budget + 0.01
    # +EV legs -> positive expected profit overall.
    assert m["total_expected_profit"] > 0


def test_leg_count_is_hard_capped_at_six():
    # Even if a tier asks for up to 12 legs and 8 are available, never exceed 6.
    legs = _legs(8, 0.60, -110)
    plan = plan_bankroll(700, 200, 30)
    greedy = [Tier("large", 1.0, 8, 12, allow_negative_ev=True)]
    m = build_matrix_from_legs(legs, plan, tiers=greedy)
    large = m["tiers"][0]
    # 8-12 leg band is impossible under the cap, so with min_legs=8 nothing builds.
    assert large["built"] is False
    # And with a reachable band, n_legs never exceeds the hard cap.
    ok = build_matrix_from_legs(legs, plan, tiers=[Tier("large", 1.0, 4, 12, allow_negative_ev=True)])
    assert ok["tiers"][0]["n_legs"] <= MAX_MATRIX_LEGS


def test_negative_ev_legs_skip_sane_tiers_but_flag_moonshot():
    # 0.50 @ -150 is a -EV leg (0.5 * 1.667 = 0.833 < 1); no +EV parlay exists.
    legs = _legs(6, 0.50, -150)
    plan = plan_bankroll(700, 200, 30)
    m = build_matrix_from_legs(legs, plan)
    by = {t["name"]: t for t in m["tiers"]}
    # the +EV-required tiers must NOT stake anything.
    assert by["small"]["built"] is False and by["small"]["stake"] == 0.0
    assert by["medium"]["built"] is False
    # the variance tier may build, but is flagged negative-EV.
    assert by["large"]["built"] is True
    assert by["large"]["positive_ev"] is False
    assert "NEGATIVE-EV" in by["large"]["note"]
    assert m["total_expected_profit"] <= 0


def test_reserve_breached_builds_nothing():
    legs = _legs(4, 0.60, -110)
    plan = plan_bankroll(150, 200, 30)  # below reserve -> daily budget 0
    m = build_matrix_from_legs(legs, plan)
    assert m["total_staked"] == 0.0
    assert all(t["built"] is False for t in m["tiers"])


def test_no_legs_builds_nothing():
    plan = plan_bankroll(700, 200, 30)
    m = build_matrix_from_legs([], plan)
    assert m["total_staked"] == 0.0
    assert all(t["built"] is False for t in m["tiers"])
