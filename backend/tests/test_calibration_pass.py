"""Calibration pass: best_shrink monitor + automatic low-confidence gating."""
from app.config import Settings
from app.model.bridge import predict_with_ensemble
from app.model.calibration import best_shrink, shrink_to_even
from app.model.inputs import (
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
)


def make_inputs(recent_ks: list[int]) -> ProjectionInputs:
    return ProjectionInputs(
        pitcher_name="Test Pitcher",
        opponent=OpponentKProfile(
            k_pct_vs_rhp=0.27, k_pct_vs_lhp=0.24, k_pct_last_14=0.295,
            k_pct_last_30=0.268, k_pct_starting_lineup=0.312,
        ),
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R, recent_start_ks=recent_ks,
            k_per_9_last_30=9.5, swinging_strike_pct=None, csw_pct=None,
        ),
        workload=ExpectedWorkload(
            expected_innings=5.8, expected_pitch_count=95,
            manager_hook_pitch_count=100,
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.30, high_k_hitters_resting=0),
    )


# --- best_shrink (monitoring fit) -------------------------------------------

def test_best_shrink_detects_overconfidence():
    # Model says 0.75 but wins only ~55% -> optimal k well below 1.
    graded = [(0.75, True)] * 55 + [(0.75, False)] * 45
    k, _ = best_shrink(graded)
    assert k < 0.5


def test_best_shrink_keeps_calibrated_model():
    # Model says 0.70 and wins 70% -> k stays near 1.
    graded = [(0.70, True)] * 70 + [(0.70, False)] * 30
    k, _ = best_shrink(graded)
    assert k >= 0.9


def test_best_shrink_is_consistent_with_shrink_to_even():
    graded = [(0.8, True), (0.8, False)]  # coin flips claimed at 80%
    k, _ = best_shrink(graded)
    assert abs(shrink_to_even(0.8, k) - 0.5) < 0.06  # shrinks ~all the way back


# --- automatic low-confidence gate -------------------------------------------

def test_low_confidence_auto_derived_from_thin_history():
    out = predict_with_ensemble(
        make_inputs(recent_ks=[7, 6, 5]),  # only 3 starts this season
        line=5.5, over_odds=-110, under_odds=-110,
    )
    assert out["low_confidence"] is True


def test_full_history_is_not_low_confidence():
    out = predict_with_ensemble(
        make_inputs(recent_ks=[7, 6, 5, 8, 7]),
        line=5.5, over_odds=-110, under_odds=-110,
    )
    assert out["low_confidence"] is False


def test_explicit_low_confidence_override_respected():
    out = predict_with_ensemble(
        make_inputs(recent_ks=[7, 6, 5, 8, 7]),
        line=5.5, over_odds=-110, under_odds=-110,
        low_confidence=True,
    )
    assert out["low_confidence"] is True


def test_shrinkage_setting_reduces_claimed_edge():
    loose = predict_with_ensemble(
        make_inputs(recent_ks=[7, 6, 5, 8, 7]), line=5.5,
        over_odds=-110, under_odds=-110,
        settings=Settings(prob_shrinkage=1.0),
    )
    tight = predict_with_ensemble(
        make_inputs(recent_ks=[7, 6, 5, 8, 7]), line=5.5,
        over_odds=-110, under_odds=-110,
        settings=Settings(prob_shrinkage=0.5),
    )
    assert abs(tight["prob_over"] - 0.5) < abs(loose["prob_over"] - 0.5)
