"""Tests for the aggregate CLV scoreboard (clv_report / the /clv route)."""

from __future__ import annotations

import csv

from app import main
from app.backtest.clv import clv_report
from fastapi.testclient import TestClient

PRED_FIELDS = [
    "date", "pitcher", "side", "over_odds", "under_odds", "bet",
]
CLOSE_FIELDS = ["date", "captured_at", "tag", "pitcher", "line", "over_odds", "under_odds"]


def _write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_clv_report_scores_flagged_bets_against_close(tmp_path):
    pred = tmp_path / "predictions.csv"
    close = tmp_path / "line_history.csv"

    # One flagged over bet we took at -110/-110; the market closed -130/+110,
    # i.e. the close implies a HIGHER over probability than we paid -> positive CLV.
    _write(pred, PRED_FIELDS, [
        {"date": "2026-06-20", "pitcher": "Gerrit Cole", "side": "over",
         "over_odds": -110, "under_odds": -110, "bet": "True"},
        # A non-bet row must be ignored entirely.
        {"date": "2026-06-20", "pitcher": "Some Body", "side": "over",
         "over_odds": -110, "under_odds": -110, "bet": "False"},
    ])
    _write(close, CLOSE_FIELDS, [
        # An open snapshot for the same pitcher must be filtered out by tag.
        {"date": "2026-06-20", "captured_at": "2026-06-20T15:00:00Z", "tag": "open",
         "pitcher": "Gerrit Cole", "line": 6.5, "over_odds": 100, "under_odds": -120},
        {"date": "2026-06-20", "captured_at": "2026-06-20T22:00:00Z", "tag": "close",
         "pitcher": "Gerrit Cole", "line": 6.5, "over_odds": -130, "under_odds": 110},
    ])

    rep = clv_report(str(pred), str(close))
    assert rep.n_bets == 1
    assert rep.n_unmatched == 0
    assert rep.mean_clv is not None and rep.mean_clv > 0  # bought below the close
    assert rep.pct_positive == 1.0
    assert rep.bets[0].beat_close is True


def test_clv_report_counts_unmatched_when_no_close(tmp_path):
    pred = tmp_path / "predictions.csv"
    close = tmp_path / "line_history.csv"
    _write(pred, PRED_FIELDS, [
        {"date": "2026-06-20", "pitcher": "Gerrit Cole", "side": "over",
         "over_odds": -110, "under_odds": -110, "bet": "True"},
    ])
    _write(close, CLOSE_FIELDS, [
        {"date": "2026-06-20", "captured_at": "2026-06-20T22:00:00Z", "tag": "close",
         "pitcher": "Different Pitcher", "line": 5.5, "over_odds": -110, "under_odds": -110},
    ])
    rep = clv_report(str(pred), str(close))
    assert rep.n_bets == 0
    assert rep.n_unmatched == 1
    assert rep.mean_clv is None
    assert "capture closing lines" in rep.verdict


def test_clv_report_missing_files_is_empty(tmp_path):
    rep = clv_report(str(tmp_path / "nope.csv"), str(tmp_path / "nope2.csv"))
    assert rep.n_bets == 0 and rep.n_unmatched == 0


def test_clv_route_returns_json(monkeypatch, tmp_path):
    pred = tmp_path / "predictions.csv"
    close = tmp_path / "line_history.csv"
    _write(pred, PRED_FIELDS, [
        {"date": "2026-06-20", "pitcher": "Gerrit Cole", "side": "over",
         "over_odds": -110, "under_odds": -110, "bet": "True"},
    ])
    _write(close, CLOSE_FIELDS, [
        {"date": "2026-06-20", "captured_at": "2026-06-20T22:00:00Z", "tag": "close",
         "pitcher": "Gerrit Cole", "line": 6.5, "over_odds": -130, "under_odds": 110},
    ])
    monkeypatch.setattr(main.settings, "predictions_log", str(pred), raising=False)
    monkeypatch.setattr(main.settings, "line_history_log", str(close), raising=False)

    client = TestClient(main.app)
    r = client.get("/clv")
    assert r.status_code == 200
    body = r.json()
    assert body["n_bets"] == 1 and body["pct_positive"] == 1.0
