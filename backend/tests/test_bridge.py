"""Tests for the ensemble -> Poisson/edge bridge."""

from __future__ import annotations

import pytest

from app.model import poisson
from app.model.bridge import evaluate_projection, predict_with_ensemble
from app.model.projection import project
from tests.test_projection import make_inputs


def test_bridge_lambda_matches_ensemble_projection():
    inputs = make_inputs()
    result = project(inputs)
    out = predict_with_ensemble(inputs, line=6.5)
    # The lambda fed to Poisson is exactly the ensemble's projected Ks.
    assert out["expected_ks"] == pytest.approx(round(result.projected_ks, 3))


def test_bridge_probs_come_from_poisson_of_lambda():
    inputs = make_inputs()
    result = project(inputs)
    out = predict_with_ensemble(inputs, line=6.5)
    assert out["prob_over"] == pytest.approx(
        round(poisson.prob_over(result.projected_ks, 6.5), 4)
    )
    assert out["prob_under"] == pytest.approx(
        round(poisson.prob_under(result.projected_ks, 6.5), 4)
    )


def test_bridge_half_line_probs_sum_to_one():
    out = predict_with_ensemble(make_inputs(), line=6.5)
    assert out["prob_over"] + out["prob_under"] == pytest.approx(1.0, abs=1e-3)


def test_bridge_without_odds_omits_edge():
    out = predict_with_ensemble(make_inputs(), line=6.5)
    assert "edge" not in out
    assert "components" in out and len(out["components"]) == 10


def test_bridge_with_odds_produces_edge_and_verdict():
    # Projection ~7.2; a soft over line at favourable odds should show edge.
    out = predict_with_ensemble(
        make_inputs(), line=5.5, over_odds=-110, under_odds=-110
    )
    assert out["side"] == "over"
    assert out["edge"] > 0
    assert out["recommendation"] in {"Strong Play", "Lean", "No Bet", "Pass"}
    assert "reasons" in out and out["reasons"]


def test_bridge_low_confidence_forces_pass():
    out = predict_with_ensemble(
        make_inputs(), line=5.5, over_odds=-110, under_odds=-110, low_confidence=True
    )
    assert out["recommendation"] == "Pass"
    assert out["bet"] is False


def test_umpire_with_bigger_zone_raises_lambda_through_bridge():
    from app.model.inputs import UmpireProfile

    base = predict_with_ensemble(make_inputs(), line=6.5)
    hot_ump = predict_with_ensemble(
        make_inputs(umpire=UmpireProfile(historical_k_rate=0.27)), line=6.5
    )
    assert hot_ump["expected_ks"] > base["expected_ks"]
    assert hot_ump["prob_over"] > base["prob_over"]


def test_evaluate_projection_accepts_bare_result():
    result = project(make_inputs())
    out = evaluate_projection(result, line=6.5)
    assert out["pitcher"] == result.pitcher_name
    assert out["expected_ks"] == pytest.approx(round(result.projected_ks, 3))
