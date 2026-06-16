"""Tests for the flag-gated type-matchup synthesis blend."""
import json

from app.model.inputs import (
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
)
from app.model.projection import project
from app.model.type_matchup import (
    archetype_regressed_rate,
    clear_priors_cache,
    load_priors,
    type_matchup_lambda,
)
from app.model.weights import ModelConfig


def _inputs(pitcher_id=None):
    return ProjectionInputs(
        pitcher_name="Test Arm",
        pitcher_id=pitcher_id,
        opponent=OpponentKProfile(
            k_pct_vs_rhp=0.22, k_pct_vs_lhp=0.22,
            k_pct_last_14=0.22, k_pct_last_30=0.22, k_pct_starting_lineup=0.22,
        ),
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R, recent_start_ks=[6, 7, 5], k_per_9_last_30=9.0
        ),
        workload=ExpectedWorkload(
            expected_innings=5.5, expected_pitch_count=95, manager_hook_pitch_count=100
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.22),
    )


def test_regressed_rate_shrinks_by_sample():
    pmarg, recent = 0.30, 0.40
    # no starts -> entirely the archetype prior
    assert archetype_regressed_rate(recent, pmarg, 0, 24, 1600) == pmarg
    # many starts -> moves toward the individual (but never fully, by design)
    hi = archetype_regressed_rate(recent, pmarg, 1000, 24, 1600)
    assert pmarg < hi < recent
    # more starts -> closer to individual
    lo = archetype_regressed_rate(recent, pmarg, 5, 24, 1600)
    assert pmarg < lo < hi


def test_lambda_with_temp_priors(tmp_path):
    p = tmp_path / "priors.json"
    p.write_text(json.dumps({
        "league_k": 0.22, "bf_per_start": 24.0,
        "pmarg": {"4": 0.30}, "pitcher_type": {"999": 4},
    }))
    lam = type_matchup_lambda(
        pitcher_id=999, recent_k_rate=0.35, opp_k_rate=0.22, expected_bf=24,
        n_starts=10, league_k=0.22, shrink_pa=1600, path=str(p),
    )
    assert lam is not None and 0 < lam < 24  # an Ks count, sane magnitude
    # unknown pitcher / no id -> no-op
    assert type_matchup_lambda(
        pitcher_id=111, recent_k_rate=0.3, opp_k_rate=0.22, expected_bf=24,
        n_starts=10, league_k=0.22, shrink_pa=1600, path=str(p)) is None
    assert type_matchup_lambda(
        pitcher_id=None, recent_k_rate=0.3, opp_k_rate=0.22, expected_bf=24,
        n_starts=10, league_k=0.22, shrink_pa=1600, path=str(p)) is None


def test_missing_priors_is_noop(tmp_path):
    clear_priors_cache()
    assert load_priors(str(tmp_path / "nope.json")) is None


def test_blend_off_by_default_is_unchanged():
    """Weight 0 (default) must leave the projection identical, id or not."""
    base = project(_inputs(pitcher_id=None)).projected_ks
    with_id = project(_inputs(pitcher_id=999999999)).projected_ks  # id absent from priors
    assert base == with_id  # default weight 0 -> no blend regardless


def test_blend_on_changes_projection_when_typed():
    """With a real exported prior + a typed pitcher, the blend shifts lambda."""
    pr = load_priors()
    if not pr or not pr.get("pitcher_type"):
        return  # artifact not present in this env; nothing to assert
    pid = int(next(iter(pr["pitcher_type"])))
    off = project(_inputs(pitcher_id=pid), ModelConfig(type_matchup_weight=0.0))
    on = project(_inputs(pitcher_id=pid), ModelConfig(type_matchup_weight=0.5))
    assert "type_matchup" in {c.name for c in on.components}
    assert "type_matchup" not in {c.name for c in off.components}
    assert on.projected_ks != off.projected_ks
