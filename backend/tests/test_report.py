"""Tests for the backtest report (grading + calibration)."""

from __future__ import annotations

import pytest

from app.model.backtest import GameOutcome
from app.report import (
    BREAK_EVEN_110,
    GradedBet,
    calibration_table,
    grade_outcome,
    render_report,
)
from tests.test_projection import make_inputs


def _bet(edge, outcome, model_prob=0.6):
    units = 100 / 110 if outcome == "win" else (-1.0 if outcome == "loss" else 0.0)
    return GradedBet("P", 5.5, 6.0, "over", model_prob, edge, 7, outcome, units)


def test_grade_outcome_win_loss_push():
    # make_inputs projects ~7.9 Ks, so the model leans OVER a 5.5 line.
    over_hit = grade_outcome(GameOutcome(inputs=make_inputs(), actual_ks=8, line=5.5))
    assert over_hit.lean == "over"
    assert over_hit.outcome == "win"
    assert over_hit.units == pytest.approx(100 / 110)

    over_miss = grade_outcome(GameOutcome(inputs=make_inputs(), actual_ks=3, line=5.5))
    assert over_miss.outcome == "loss"
    assert over_miss.units == -1.0

    # Integer line landed on exactly -> push.
    push = grade_outcome(GameOutcome(inputs=make_inputs(), actual_ks=8, line=8.0))
    assert push.outcome == "push"
    assert push.units == 0.0


def test_grade_outcome_none_without_line():
    assert grade_outcome(GameOutcome(inputs=make_inputs(), actual_ks=7, line=None)) is None


def test_calibration_table_buckets_and_winrate():
    bets = [
        _bet(0.03, "win"), _bet(0.04, "loss"),          # 0-5%
        _bet(0.07, "win"), _bet(0.08, "win"),           # 5-10%
        _bet(0.15, "loss"), _bet(0.15, "loss"),         # 10-20%
    ]
    rows = {r["bucket"]: r for r in calibration_table(bets)}
    assert rows["0%-5%"]["plays"] == 2
    assert rows["0%-5%"]["actual_win"] == pytest.approx(0.5)
    assert rows["5%-10%"]["actual_win"] == pytest.approx(1.0)
    # The overconfidence signal: a 10-20% edge bucket that went 0-for-2.
    assert rows["10%-20%"]["actual_win"] == pytest.approx(0.0)


def test_calibration_excludes_pushes():
    bets = [_bet(0.07, "win"), _bet(0.07, "push")]
    rows = {r["bucket"]: r for r in calibration_table(bets)}
    assert rows["5%-10%"]["plays"] == 1  # push not counted


def test_render_report_small_sample_warning():
    dataset = [GameOutcome(inputs=make_inputs(), actual_ks=8, line=5.5)]
    text = render_report("2026-06-09", "2026-06-09", dataset)
    assert "BACKTEST REPORT" in text
    assert "variance, not edge" in text  # n<100 warning fires
