"""Tests for the strikeout projection engine."""

from __future__ import annotations

import pytest

from app.model import (
    ExpectedWorkload,
    Handedness,
    Lean,
    LineupStrength,
    ModelConfig,
    OpponentKProfile,
    PitchMixMatchup,
    PitchUsage,
    PitcherRecentForm,
    ProjectionInputs,
    UmpireProfile,
    evaluate_bet,
    project,
)


def make_inputs(**overrides) -> ProjectionInputs:
    base = dict(
        pitcher_name="Test Pitcher",
        opponent=OpponentKProfile(
            k_pct_vs_rhp=0.27,
            k_pct_vs_lhp=0.24,
            k_pct_last_14=0.295,
            k_pct_last_30=0.268,
            k_pct_starting_lineup=0.312,
        ),
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R,
            recent_start_ks=[8, 6, 9, 8, 7],
            k_per_9_last_30=9.5,
            swinging_strike_pct=0.13,
            csw_pct=0.30,
        ),
        workload=ExpectedWorkload(
            expected_innings=5.8,
            expected_pitch_count=95,
            manager_hook_pitch_count=100,
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.30, high_k_hitters_resting=0),
        umpire=UmpireProfile(historical_k_rate=0.23, called_strike_rate=0.50),
        pitch_mix=PitchMixMatchup(
            pitches=[
                PitchUsage(pitch_type="SL", usage_pct=0.40, opponent_whiff_pct=0.32),
                PitchUsage(pitch_type="FF", usage_pct=0.45, opponent_whiff_pct=0.20),
                PitchUsage(pitch_type="CH", usage_pct=0.15, opponent_whiff_pct=0.28),
            ]
        ),
    )
    base.update(overrides)
    return ProjectionInputs(**base)


def test_projection_is_realistic():
    result = project(make_inputs())
    # A mid-tier strikeout starter against a high-K lineup should land ~6-9 Ks.
    assert 6.0 <= result.projected_ks <= 9.0
    # Expected BF = 5.8 IP * 4.3 batters/inning.
    assert result.expected_batters_faced == pytest.approx(5.8 * 4.3)


def test_all_seven_components_present():
    result = project(make_inputs())
    names = {c.name for c in result.components}
    assert names == {
        "opponent_k_profile",
        "pitcher_recent_form",
        "expected_innings",
        "lineup_strength",
        "umpire",
        "pitch_count",
        "pitch_mix",
    }


def test_projection_equals_weighted_blend_of_components():
    result = project(make_inputs())
    blended = sum(c.weight * c.estimate_ks for c in result.components)
    assert result.projected_ks == pytest.approx(blended)


def test_recent_form_uses_mean_of_recent_starts():
    result = project(make_inputs())
    form = result.component("pitcher_recent_form")
    assert form.estimate_ks == pytest.approx(7.6)  # mean of [8,6,9,8,7]


def test_recent_form_falls_back_to_k_per_9_when_no_starts():
    inputs = make_inputs(
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R, recent_start_ks=[], k_per_9_last_30=9.5
        )
    )
    result = project(inputs)
    form = result.component("pitcher_recent_form")
    # bf * (k_per_9 / (4.3*9))
    bf = 5.8 * 4.3
    assert form.estimate_ks == pytest.approx(bf * (9.5 / (4.3 * 9)))


def test_resting_high_k_hitters_lowers_projection():
    strong = project(make_inputs(lineup=LineupStrength(projected_lineup_k_pct=0.31)))
    weak = project(
        make_inputs(
            lineup=LineupStrength(projected_lineup_k_pct=0.22, high_k_hitters_resting=3)
        )
    )
    assert weak.projected_ks < strong.projected_ks


def test_early_manager_hook_trims_volume():
    full = project(make_inputs())
    hooked = project(
        make_inputs(
            workload=ExpectedWorkload(
                expected_innings=5.8,
                expected_pitch_count=95,
                manager_hook_pitch_count=72,  # ~4.5 IP at 16 pitches/inning
            )
        )
    )
    full_pc = full.component("pitch_count").estimate_ks
    hooked_pc = hooked.component("pitch_count").estimate_ks
    assert hooked_pc < full_pc


def test_bigger_strike_zone_umpire_raises_estimate():
    base = project(make_inputs())
    pitcher_friendly = project(
        make_inputs(umpire=UmpireProfile(historical_k_rate=0.26))
    )
    assert (
        pitcher_friendly.component("umpire").estimate_ks
        > base.component("umpire").estimate_ks
    )


def test_missing_optional_data_defaults_to_neutral():
    inputs = make_inputs(umpire=None, pitch_mix=None)
    result = project(inputs)
    neutral = result.component("expected_innings").estimate_ks
    assert result.component("umpire").estimate_ks == pytest.approx(neutral)
    assert result.component("pitch_mix").estimate_ks == pytest.approx(neutral)


def test_handedness_selects_correct_opponent_k_pct():
    rhp = project(make_inputs())
    lefty_form = PitcherRecentForm(
        throws=Handedness.L, recent_start_ks=[8, 6, 9, 8, 7], k_per_9_last_30=9.5
    )
    lhp = project(make_inputs(pitcher_form=lefty_form))
    # Opponent strikes out more vs RHP (0.27) than LHP (0.24), so the
    # opponent-profile lens should be higher for the righty.
    assert (
        rhp.component("opponent_k_profile").estimate_ks
        > lhp.component("opponent_k_profile").estimate_ks
    )


def test_evaluate_bet_leans():
    result = project(make_inputs())
    over = evaluate_bet(result, line=result.projected_ks - 1.0)
    under = evaluate_bet(result, line=result.projected_ks + 1.0)
    push = evaluate_bet(result, line=result.projected_ks)
    assert over.lean is Lean.OVER
    assert under.lean is Lean.UNDER
    assert push.lean is Lean.PASS
    assert over.edge_ks == pytest.approx(1.0)


def test_component_weights_must_sum_to_one():
    from app.model import ComponentWeights

    with pytest.raises(ValueError):
        ComponentWeights(opponent_k_profile=0.50)  # rest stay default -> sum > 1


def test_log5_keeps_elite_pitcher_above_naive_average():
    from app.model.projection import _log5_matchup

    # Ace (30% K) vs a league-average lineup (22%), league 22%.
    p, o, lg = 0.30, 0.22, 0.22
    matchup = _log5_matchup(p, o, lg)
    naive = (p + o) / 2
    # log5 must NOT regress him toward the lineup the way averaging did...
    assert matchup > naive
    # ...and against a league-average opponent the matchup ~= his own rate.
    assert matchup == pytest.approx(p, abs=0.005)


def test_log5_compounds_two_below_average_rates_downward():
    from app.model.projection import _log5_matchup

    # A weak strikeout pitcher vs a contact-heavy lineup -> below both rates.
    matchup = _log5_matchup(0.18, 0.18, 0.22)
    assert matchup < 0.18


def test_elite_pitcher_vs_average_lineup_not_dragged_under():
    # k/9 ~ 11.6 -> pitcher K% ~ 0.30; opponent league-average ~ 0.22.
    avg_opp = OpponentKProfile(
        k_pct_vs_rhp=0.22, k_pct_vs_lhp=0.22, k_pct_last_14=0.22,
        k_pct_last_30=0.22, k_pct_starting_lineup=0.22,
    )
    form = PitcherRecentForm(throws=Handedness.R, recent_start_ks=[9, 10, 8, 9, 9], k_per_9_last_30=11.6)
    inputs = make_inputs(
        opponent=avg_opp,
        pitcher_form=form,
        lineup=LineupStrength(projected_lineup_k_pct=0.22),
        umpire=None,
        pitch_mix=None,
    )
    result = project(inputs)
    bf = result.expected_batters_faced
    # The matchup-based opponent lens should reflect ~the pitcher's own ~30% rate
    # (not the old naive average of ~26% that manufactured false unders).
    opp_est = result.component("opponent_k_profile").estimate_ks
    assert opp_est / bf > 0.27  # well above the 0.26 the average would have given


def test_custom_weights_change_projection():
    from app.model import ComponentWeights

    # Put all weight on the opponent profile.
    cfg = ModelConfig(
        weights=ComponentWeights(
            opponent_k_profile=1.0,
            pitcher_recent_form=0.0,
            expected_innings=0.0,
            lineup_strength=0.0,
            umpire=0.0,
            pitch_count=0.0,
            pitch_mix=0.0,
        )
    )
    result = project(make_inputs(), cfg)
    assert result.projected_ks == pytest.approx(
        result.component("opponent_k_profile").estimate_ks
    )
