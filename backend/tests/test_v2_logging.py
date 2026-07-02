"""Tests for v2 slate -> predictions-log mapping (main._v2_log_rows).

Pins the unification decision: the graded record's flagged bets = the dashboard's
featured card (selected), and only priced (ok) rows are logged.
"""
from __future__ import annotations

from app.main import _v2_log_rows


def test_only_ok_rows_logged_with_bet_from_selected():
    rows = [
        {"status": "ok", "pitcher": "A", "selected": True, "side": "under", "line": 5.5},
        {"status": "ok", "pitcher": "B", "selected": False, "side": "over", "line": 4.5},
        {"status": "no_prop", "pitcher": "C"},                    # dropped (unpriced)
        {"status": "probable_not_announced", "pitcher": "TBD"},   # dropped
    ]
    out = _v2_log_rows(rows, "2026-07-02")
    assert len(out) == 2
    assert all(r["status"] == "ok" for r in out)
    assert out[0]["bet"] is True and out[0]["date"] == "2026-07-02"   # card member -> bet
    assert out[1]["bet"] is False                                     # priced but off-card


def test_existing_per_row_date_is_preserved():
    rows = [{"status": "ok", "selected": True, "date": "2026-06-30"}]
    assert _v2_log_rows(rows, "2026-07-02")[0]["date"] == "2026-06-30"


def test_missing_selected_defaults_to_not_bet():
    # vetoed rows never went through select_card, so they carry no 'selected' key
    rows = [{"status": "ok", "pitcher": "vetoed"}]
    assert _v2_log_rows(rows, "2026-07-02")[0]["bet"] is False
