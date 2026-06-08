"""Tests for the model backtesting + weight-tuning module."""

from __future__ import annotations

import math

import pytest

from app.model import (
    ComponentWeights,
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    ModelConfig,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
    accuracy_metrics,
    betting_metrics,
    make_synthetic_dataset,
    project,
    run_backtest,
    tune_weights,
)
from app.model.backtest import GameOutcome


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
        ),
        workload=ExpectedWorkload(
            expected_innings=5.8,
            expected_pitch_count=95,
            manager_hook_pitch_count=100,
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.30),
    )
    base.update(overrides)
    return ProjectionInputs(**base)


def _outcome(actual_ks: int, line: float | None = None, **overrides) -> GameOutcome:
    return GameOutcome(inputs=make_inputs(**overrides), actual_ks=actual_ks, line=line)


# --------------------------------------------------------------------------- #
# Accuracy metrics
# --------------------------------------------------------------------------- #
def test_accuracy_metrics_by_hand():
    # Same inputs -> same projection p for every record.
    p = project(make_inputs()).projected_ks
    actuals = [round(p), round(p) - 2, round(p) + 1]
    ds = [_outcome(a) for a in actuals]
    m = accuracy_metrics(ds)

    errs = [p - a for a in actuals]
    assert m.n == 3
    assert m.mae == pytest.approx(sum(abs(e) for e in errs) / 3)
    assert m.rmse == pytest.approx(math.sqrt(sum(e * e for e in errs) / 3))
    assert m.bias == pytest.approx(sum(errs) / 3)


def test_accuracy_empty_dataset():
    m = accuracy_metrics([])
    assert m.n == 0 and m.mae == 0.0 and m.rmse == 0.0 and m.bias == 0.0


# --------------------------------------------------------------------------- #
# Betting metrics
# --------------------------------------------------------------------------- #
def test_betting_metrics_known_outcomes():
    p = project(make_inputs()).projected_ks  # ~7.x
    # Line well below projection -> lean OVER.
    over_win = _outcome(actual_ks=round(p) + 3, line=p - 2.5)   # over hits -> win
    over_loss = _outcome(actual_ks=round(p) - 4, line=p - 2.5)  # over misses -> loss
    # Line well above projection -> lean UNDER.
    under_win = _outcome(actual_ks=round(p) - 4, line=p + 2.5)  # under hits -> win
    ds = [over_win, over_loss, under_win]

    m = betting_metrics(ds)
    assert m.n_plays == 3
    assert m.wins == 2 and m.losses == 1 and m.pushes == 0
    assert m.win_rate == pytest.approx(2 / 3)
    # profit = 0.909 + (-1) + 0.909 = 0.818 over 3 plays.
    expected_units = (2 * (100 / 110) - 1.0) / 3
    assert m.roi == pytest.approx(expected_units, abs=1e-6)


def test_push_excluded_from_winrate_and_zero_units():
    p = project(make_inputs()).projected_ks
    line = float(round(p - 2.0))  # integer line, lean OVER
    push = _outcome(actual_ks=int(line), line=line)   # actual == line -> push
    win = _outcome(actual_ks=int(line) + 3, line=line)  # over -> win
    m = betting_metrics([push, win])
    assert m.pushes == 1 and m.wins == 1 and m.losses == 0
    assert m.n_plays == 2
    assert m.win_rate == pytest.approx(1.0)  # push excluded from rate
    # units: push 0 + win 0.909 over 2 plays.
    assert m.roi == pytest.approx((100 / 110) / 2, abs=1e-6)


def test_records_without_line_ignored_in_betting():
    ds = [_outcome(7), _outcome(5)]  # no lines
    m = betting_metrics(ds)
    assert m.n_plays == 0 and m.roi == 0.0


def test_run_backtest_skips_betting_without_lines():
    res = run_backtest([_outcome(7), _outcome(8)])
    assert res.betting is None
    assert res.accuracy.n == 2


# --------------------------------------------------------------------------- #
# Tuning
# --------------------------------------------------------------------------- #
def test_synthetic_dataset_is_deterministic_and_plausible():
    a = make_synthetic_dataset(n=20, seed=42)
    b = make_synthetic_dataset(n=20, seed=42)
    assert len(a) == 20
    assert [g.actual_ks for g in a] == [g.actual_ks for g in b]
    for g in a:
        assert 0 <= g.actual_ks <= 20
        assert g.line is not None


def test_tune_weights_returns_valid_simplex():
    ds = make_synthetic_dataset(n=60, seed=1)
    best, score = tune_weights(ds, objective="mae", n_random=80, n_refine=20, seed=7)
    vals = list(best.as_dict().values())
    assert all(v >= 0 for v in vals)
    assert sum(vals) == pytest.approx(1.0, abs=1e-6)
    assert score >= 0
    # A ComponentWeights instance only exists if the sum-to-1 validator passed.
    assert isinstance(best, ComponentWeights)


def test_tune_weights_improves_mae_over_default():
    ds = make_synthetic_dataset(n=120, seed=3)
    default_mae = accuracy_metrics(ds, ModelConfig()).mae
    best, tuned_mae = tune_weights(ds, objective="mae", n_random=150, n_refine=40, seed=11)
    assert tuned_mae <= default_mae
    # And re-running the model with the tuned weights reproduces that MAE.
    cfg = ModelConfig(weights=best)
    assert accuracy_metrics(ds, cfg).mae == pytest.approx(tuned_mae)


def test_tune_weights_roi_objective_is_valid():
    ds = make_synthetic_dataset(n=120, seed=5)
    best, roi = tune_weights(ds, objective="roi", n_random=80, n_refine=20, seed=9)
    assert sum(best.as_dict().values()) == pytest.approx(1.0, abs=1e-6)
    # Tuned ROI should be at least as good as default-weight ROI.
    default_roi = betting_metrics(ds, ModelConfig()).roi
    assert roi >= default_roi - 1e-9
