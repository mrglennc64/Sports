"""Tests for out-of-sample calibration validation (app.backtest.calibration_validate).

These pin the two properties that make the tool safe to trust:
  * the calibrators are MONOTONIC (never invert the model into an anti-signal), and
  * the recommendation is CONSERVATIVE on thin / noisy samples (never endorses
    fitting small-sample noise — the failure mode of a per-band lookup).
"""
from __future__ import annotations

import math

from app.backtest.settle import SettledBet
from app.backtest.calibration_validate import (
    apply_platt,
    oos_validate,
    pairs_with_dates,
    platt_fit,
)


def _bet(date: str, model_prob: float | None, won: bool | None) -> SettledBet:
    result = "push" if won is None else ("win" if won else "loss")
    return SettledBet(
        date=date, pitcher="p", side="over", line=5.5, odds=-110, edge=0.05,
        model_prob=model_prob, flagged_bet=True, expected_ks=6.0, actual_ks=6,
        result=result, profit_units=0.0,
    )


def _day(i: int) -> str:
    # distinct, monotonically-increasing dates (one per index), like real slates
    from datetime import date, timedelta
    return (date(2026, 1, 1) + timedelta(days=i)).isoformat()


# ---- helper properties -----------------------------------------------------

def test_apply_platt_identity_is_noop():
    # (a, b) = (0, 1) must return the input unchanged (within clamp eps).
    for p in (0.1, 0.3, 0.5, 0.73, 0.9):
        assert abs(apply_platt(p, 0.0, 1.0) - p) < 1e-6


def test_apply_platt_is_monotonic_and_clamped():
    a, b = -0.4, 0.6
    prev = -1.0
    for i in range(1, 100):
        p = i / 100
        c = apply_platt(p, a, b)
        assert 0.0 <= c <= 1.0
        assert c >= prev  # non-decreasing in p (b >= 0)
        prev = c


def test_platt_fit_b_never_negative():
    # Even adversarial (anti-correlated) data must not yield an inverting b < 0.
    pairs = [(0.9, 0), (0.8, 0), (0.2, 1), (0.1, 1)] * 10
    _, b = platt_fit(pairs)
    assert b >= 0.0


def test_platt_recovers_overconfidence():
    # Build data that is systematically OVERCONFIDENT: claimed prob is more extreme
    # than the truth. A good fit pulls it back -> b < 1.
    pairs: list[tuple[float, int]] = []
    # claimed 0.8 but truly 0.6; claimed 0.2 but truly 0.4
    for _ in range(60):
        pairs.append((0.8, 1))
        pairs.append((0.8, 0))  # 50% of the 0.8 group... build ~60% below
    # 0.8 claimed, realize ~0.6
    pairs = [(0.8, 1)] * 60 + [(0.8, 0)] * 40 + [(0.2, 1)] * 40 + [(0.2, 0)] * 60
    a, b = platt_fit(pairs)
    # overconfident -> slope < 1 (compress toward the middle)
    assert b < 1.0
    # a 0.8 claim should be pulled down toward its realized ~0.6
    assert apply_platt(0.8, a, b) < 0.8


def test_pairs_with_dates_drops_push_and_none():
    settled = [
        _bet("2026-04-01", 0.6, True),
        _bet("2026-04-02", 0.7, None),   # push -> dropped
        _bet("2026-04-03", None, False),  # no model_prob -> dropped
        _bet("2026-04-04", 0.55, False),
    ]
    pairs = pairs_with_dates(settled)
    assert len(pairs) == 2
    assert {p[1] for p in pairs} == {0.6, 0.55}


# ---- OOS split + recommendation behavior -----------------------------------

def test_too_few_predictions_keeps_calibration_off():
    settled = [_bet(_day(i), 0.6, i % 2 == 0) for i in range(40)]
    rep = oos_validate(settled)
    assert rep.recommended_method == "none"
    assert "too few" in rep.recommendation.lower() or "keep" in rep.recommendation.lower()


def test_provisional_below_verdict_bar_does_not_enable():
    # 150 rows: enough to split, but below the 200-sample trust bar -> never enable.
    settled = [_bet(_day(i), 0.65, i % 3 != 0) for i in range(150)]
    rep = oos_validate(settled)
    assert rep.n_train > 0 and rep.n_test > 0
    assert rep.recommended_method == "none"
    assert "provisional" in rep.recommendation.lower()


def test_oos_split_is_chronological_and_disjoint():
    settled = [_bet(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 0.6, i % 2 == 0)
               for i in range(300)]
    rep = oos_validate(settled, train_frac=0.7)
    assert rep.n_train + rep.n_test == rep.n_total
    assert rep.n_total == 300
    # train ends no later than test begins (chronological, no leakage)
    assert rep.train_date_range[1] <= rep.test_date_range[0]


def test_well_calibrated_data_yields_no_recommendation():
    # If the model is already honest, no calibrator should clear the margin.
    # claimed 0.6 wins ~60%, claimed 0.4 wins ~40%, claimed 0.5 wins ~50%.
    settled: list[SettledBet] = []
    i = 0
    for p, wins, total in ((0.6, 6, 10), (0.4, 4, 10), (0.5, 5, 10)):
        for _ in range(10):  # 100 of each claimed level -> 300 total, large enough
            for w in range(total):
                settled.append(_bet(_day(i), p, w < wins))
                i += 1
    rep = oos_validate(settled)
    assert rep.recommended_method == "none"


def test_single_date_is_flagged_and_never_enabled():
    # The real n=147 case: everything graded on ONE slate. No temporal holdout,
    # so the tool must flag it and refuse to enable regardless of any in-sample gain.
    settled = [_bet("2026-06-28", 0.65, i % 3 != 0) for i in range(160)]
    rep = oos_validate(settled)
    assert rep.temporal_holdout is False
    assert rep.recommended_method == "none"
    assert "one slate" in rep.recommendation.lower() or "same date" in rep.recommendation.lower()


def test_multi_date_has_temporal_holdout():
    settled = [_bet(_day(i), 0.6, i % 2 == 0) for i in range(300)]
    rep = oos_validate(settled)
    assert rep.temporal_holdout is True


def test_report_always_has_three_method_scores_when_split():
    settled = [_bet(_day(i), 0.6, i % 2 == 0) for i in range(300)]
    rep = oos_validate(settled)
    assert set(rep.test_scores.keys()) == {"baseline", "shrink", "platt"}
    for s in rep.test_scores.values():
        assert s["brier"] is not None and s["log_loss"] is not None
