"""Tests for the factor-projection backfill — locks in the collinearity finding.

The headline result of Step 1: with the minor factors neutral (no umpire / pitch-mix /
weather / catcher / bullpen data), 8 of the 10 ensemble components are the SAME number
(matchup_estimate), and only recent_form and lineup are distinct. This test pins that
structural fact so a future refactor can't silently break the assumption the weight
work rests on.
"""
from __future__ import annotations

from app.fit.factor_backfill import COMPONENT_ORDER
from app.model.inputs import (ExpectedWorkload, Handedness, LineupStrength,
                              OpponentKProfile, PitcherRecentForm, ProjectionInputs)
from app.model.projection import project


def _inputs():
    return ProjectionInputs(
        pitcher_name="test",
        opponent=OpponentKProfile(k_pct_vs_rhp=0.24, k_pct_vs_lhp=0.23,
                                  k_pct_last_14=0.24, k_pct_last_30=0.24,
                                  k_pct_starting_lineup=0.25),
        pitcher_form=PitcherRecentForm(throws=Handedness.R, recent_start_ks=[7, 6, 8, 5, 7],
                                       k_per_9_last_30=9.5),
        workload=ExpectedWorkload(expected_innings=5.8, expected_pitch_count=93,
                                  manager_hook_pitch_count=103),
        lineup=LineupStrength(projected_lineup_k_pct=0.25),
        # minor factors left None -> neutral
    )


def test_eight_matchup_components_are_identical():
    comps = {c.name: c.estimate_ks for c in project(_inputs()).components}
    matchup_family = ["opponent_k_profile", "expected_innings", "umpire",
                      "pitch_count", "pitch_mix", "bullpen_leash", "weather", "catcher_framing"]
    vals = [comps[c] for c in matchup_family]
    # all eight are the SAME number (the collinearity that bounds weight optimization)
    assert max(vals) - min(vals) < 1e-9, "matchup-family components should be identical when minor factors are neutral"
    # the two genuinely distinct signals differ from it
    assert abs(comps["pitcher_recent_form"] - vals[0]) > 1e-6
    assert abs(comps["lineup_strength"] - vals[0]) > 1e-9


def test_component_order_matches_projection_output():
    names = [c.name for c in project(_inputs()).components]
    assert names == COMPONENT_ORDER
