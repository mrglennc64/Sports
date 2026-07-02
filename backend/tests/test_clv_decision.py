"""The CLV keep/kill decision checkpoint.

clv_decision layers two honest gates: a decision-grade sample (n vs target) and a
95% CI on the mean CLV that must clear zero before we call keep or kill.
"""
from app.backtest.clv import DECISION_TARGET_N, clv_decision


def test_empty_is_gathering():
    d = clv_decision([])
    assert d.status == "gathering"
    assert d.decided is False
    assert d.n == 0 and d.progress_pct == 0.0
    assert d.mean_clv is None
    assert "0 of" in d.headline


def test_below_target_is_never_decided():
    # A strong positive sample, but far short of a decision-grade count.
    d = clv_decision([0.05] * 10, target_n=200)
    assert d.status == "gathering"
    assert d.decided is False
    assert d.n == 10
    assert d.mean_clv == 0.05
    # The provisional lean still surfaces the direction.
    assert "leaning KEEP" in d.headline or "NOT YET DECIDED" in d.headline


def test_below_target_reports_lean_from_ci():
    # Tiny, noisy sample straddling zero -> no edge yet, still gathering.
    d = clv_decision([0.2, -0.2, 0.1, -0.1], target_n=200)
    assert d.status == "gathering"
    assert d.signal == "inconclusive"


def test_decided_keep_when_ci_above_zero():
    vals = [0.01, 0.02] * 100  # n=200, mean 0.015, tight -> CI clears zero
    d = clv_decision(vals, target_n=200)
    assert d.decided is True
    assert d.status == "keep"
    assert d.signal == "keep"
    assert d.ci95_low is not None and d.ci95_low > 0
    assert "KEEP" in d.headline


def test_decided_kill_when_ci_below_zero():
    vals = [-0.02, -0.03] * 100  # n=200, clearly negative
    d = clv_decision(vals, target_n=200)
    assert d.decided is True
    assert d.status == "kill"
    assert d.ci95_high is not None and d.ci95_high < 0
    assert "KILL" in d.headline


def test_decided_inconclusive_when_ci_straddles_zero():
    # Mean near zero with wide spread -> CI straddles 0 even at target size.
    vals = ([0.3, -0.3] * 100)  # n=200, mean 0, huge variance
    d = clv_decision(vals, target_n=200)
    assert d.decided is True
    assert d.status == "inconclusive"
    assert d.ci95_low is not None and d.ci95_low < 0 < d.ci95_high
    assert "INCONCLUSIVE" in d.headline


def test_progress_pct_caps_at_one():
    d = clv_decision([0.01] * 400, target_n=200)
    assert d.progress_pct == 1.0


def test_default_target_is_used():
    d = clv_decision([0.01] * 5)
    assert d.target_n == DECISION_TARGET_N
