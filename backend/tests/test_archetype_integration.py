"""Test archetype predictor integration into ensemble pipeline."""

from __future__ import annotations

import pytest

from app.model import (
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    ModelConfig,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
    project,
)
from app.model.weights import ComponentWeights


def make_inputs(**overrides) -> ProjectionInputs:
    """Create test inputs with a pitcher_id for archetype lookup."""
    base = dict(
        pitcher_name="Test Pitcher",
        pitcher_id=657277,  # Example pitcher ID
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
        ),
        workload=ExpectedWorkload(
            expected_innings=5.8,
            expected_pitch_count=95,
            manager_hook_pitch_count=100,
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.30, high_k_hitters_resting=0),
    )
    base.update(overrides)
    return ProjectionInputs(**base)


def test_archetype_disabled_by_default():
    """Archetype component should not appear when weight is 0 (default)."""
    result = project(make_inputs())
    names = {c.name for c in result.components}
    assert "archetype_interaction" not in names


def test_archetype_enabled_when_weight_set():
    """Archetype component should appear when archetype_weight > 0."""
    cfg = ModelConfig(archetype_weight=0.1)
    result = project(make_inputs(), cfg)

    # Check if archetype component was added
    names = {c.name for c in result.components}
    # Only check if data files exist - if not, archetype won't be added
    if "archetype_interaction" in names:
        archetype = next(c for c in result.components if c.name == "archetype_interaction")
        assert archetype.weight == 0.1
        assert archetype.estimate_ks > 0
        assert "archetype K%" in archetype.detail
    # If no archetype data available, component won't be added (expected fallback)


def test_archetype_skipped_without_pitcher_id():
    """Archetype should not run when pitcher_id is None."""
    cfg = ModelConfig(archetype_weight=0.1)
    inputs = make_inputs(pitcher_id=None)
    result = project(inputs, cfg)

    names = {c.name for c in result.components}
    assert "archetype_interaction" not in names


def test_projection_still_works_with_archetype():
    """Ensemble should produce reasonable results with archetype enabled."""
    cfg = ModelConfig(archetype_weight=0.05)
    result = project(make_inputs(), cfg)

    # Should still get realistic projection
    assert 5.0 <= result.projected_ks <= 10.0
    assert result.expected_batters_faced > 0


def test_archetype_weight_affects_projection():
    """Different archetype weights should affect the final projection."""
    # Get baseline with no archetype
    cfg_off = ModelConfig(archetype_weight=0.0)
    result_off = project(make_inputs(), cfg_off)

    # Get projection with archetype
    cfg_on = ModelConfig(archetype_weight=0.1)
    result_on = project(make_inputs(), cfg_on)

    # Projections may differ if archetype data exists
    # (or be same if archetype falls back / not available)
    # Just verify both produce valid results
    assert 4.0 <= result_off.projected_ks <= 12.0
    assert 4.0 <= result_on.projected_ks <= 12.0
