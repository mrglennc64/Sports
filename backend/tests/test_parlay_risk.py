"""Tests for the honest per-parlay risk label (app.parlay_pipeline.parlay_risk)."""
from __future__ import annotations

from dataclasses import dataclass

from app.parlay_pipeline import parlay_risk


@dataclass
class _EV:  # minimal stand-in: parlay_risk only reads these three fields
    model_prob: float
    n_legs: int
    kelly: float


def test_tier_from_win_prob_and_leg_count():
    assert parlay_risk(_EV(0.25, 3, 0.02))["tier"] == "high"    # low win prob
    assert parlay_risk(_EV(0.55, 4, 0.02))["tier"] == "high"    # 4+ legs
    assert parlay_risk(_EV(0.40, 2, 0.02))["tier"] == "medium"  # mid win prob
    assert parlay_risk(_EV(0.55, 3, 0.02))["tier"] == "medium"  # exactly 3 legs
    assert parlay_risk(_EV(0.60, 2, 0.02))["tier"] == "low"     # high prob, short


def test_recommended_stake_is_the_parlays_own_capped_kelly():
    r = parlay_risk(_EV(0.60, 2, 0.03), bankroll=1000)
    assert r["kelly_fraction"] == 0.03
    assert r["recommended_stake"] == 30.0          # 1000 * 0.03, not an invented fraction


def test_no_bankroll_leaves_stake_none():
    assert parlay_risk(_EV(0.60, 2, 0.03))["recommended_stake"] is None


def test_loses_about_and_note_surface_the_win_probability():
    r = parlay_risk(_EV(0.25, 3, 0.02))
    assert r["loses_about"] == "~1 in 4"
    assert r["win_prob"] == 0.25
    assert "UNPROVEN" in r["note"]
