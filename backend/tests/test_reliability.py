"""Reliability/calibration scoring over settled predictions + the /calibration route."""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.backtest.reliability import reliability_report
from app.backtest.settle import settle_row


def _bet(model_prob, won, side="over", line="5.5"):
    """A settled bet at the given claimed probability, forced to win/lose.

    side=over, line=5.5: actual 7 Ks -> over wins, actual 3 -> over loses.
    """
    row = {
        "date": "2026-06-07", "pitcher": "Test", "pitcher_id": "1",
        "side": side, "line": line, "over_odds": "-110", "under_odds": "-110",
        "edge": "0.05", "expected_ks": "6", "model_prob": str(model_prob),
        "bet": "True",
    }
    return settle_row(row, actual_ks=7 if won else 3)


# --- metrics ----------------------------------------------------------------

def test_perfect_predictions_score_zero_brier():
    bets = [_bet(1.0, True) for _ in range(50)] + [_bet(0.0, False) for _ in range(50)]
    rep = reliability_report(bets)
    assert rep.n == 100
    assert rep.brier == pytest.approx(0.0, abs=1e-6)
    assert rep.skill is True  # beats the base-rate reference


def test_brier_value_matches_formula():
    # Two bets: claim 0.8 and win, claim 0.6 and lose.
    # Brier = ((0.8-1)^2 + (0.6-0)^2)/2 = (0.04 + 0.36)/2 = 0.20
    bets = [_bet(0.8, True), _bet(0.6, False)]
    rep = reliability_report(bets)
    assert rep.brier == pytest.approx(0.20, abs=1e-9)


def test_reliability_bucket_tracks_realized_rate():
    # 100 plays all claimed at 0.70; exactly 70 win -> a calibrated 0.7 bucket.
    bets = [_bet(0.70, True) for _ in range(70)] + [_bet(0.70, False) for _ in range(30)]
    rep = reliability_report(bets)
    assert len(rep.bins) == 1  # all predictions share one probability -> one bucket
    bucket = rep.bins[0]
    assert bucket.n == 100
    assert bucket.avg_predicted == pytest.approx(0.70, abs=1e-9)
    assert bucket.actual_rate == pytest.approx(0.70, abs=1e-9)
    assert bucket.gap == pytest.approx(0.0, abs=1e-9)
    assert rep.ece == pytest.approx(0.0, abs=1e-9)


def test_overconfident_model_shows_negative_gap():
    # Claims 0.90 but only wins 50% -> realized rate well below claimed.
    bets = [_bet(0.90, i < 50) for i in range(100)]
    rep = reliability_report(bets)
    assert len(rep.bins) == 1
    bucket = rep.bins[0]
    assert bucket.actual_rate == pytest.approx(0.50, abs=1e-9)
    assert bucket.gap < 0  # actual below claimed = overconfident
    # Brier = (0.01 + 0.81)/2 = 0.41 > base-rate reference 0.25 -> no skill.
    assert rep.skill is False
    assert rep.ece > 0.3


def test_pushes_and_missing_prob_are_excluded():
    good = _bet(0.7, True)
    push = settle_row({**_row_base(), "side": "over", "line": "6",
                       "model_prob": "0.7"}, actual_ks=6)  # line landed -> push
    no_prob = settle_row({**_row_base(), "side": "over", "line": "5.5"}, actual_ks=7)
    rep = reliability_report([good, push, no_prob])
    assert rep.n == 1  # only the decided, probability-carrying bet counts


def test_empty_input_is_friendly():
    rep = reliability_report([])
    assert rep.n == 0 and rep.brier is None
    assert "no decided predictions" in rep.verdict


def _row_base():
    return {
        "date": "2026-06-07", "pitcher": "Test", "pitcher_id": "1",
        "over_odds": "-110", "under_odds": "-110", "edge": "0.05",
        "expected_ks": "6", "bet": "True",
    }


# --- route ------------------------------------------------------------------

def test_calibration_route(monkeypatch):
    bets = [_bet(0.7, True) for _ in range(70)] + [_bet(0.7, False) for _ in range(30)]
    monkeypatch.setattr(main, "settle_predictions", lambda path: bets)
    client = TestClient(main.app)
    resp = client.get("/calibration")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n"] == 100
    assert body["base_rate"] == pytest.approx(0.70, abs=1e-9)
    assert len(body["bins"]) == 1
    assert body["bins"][0]["avg_predicted"] == pytest.approx(0.70, abs=1e-9)
