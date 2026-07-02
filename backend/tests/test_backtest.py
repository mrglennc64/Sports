import csv

import httpx
import pytest
import respx

from app.backtest.clv import clv_for_side, find_closing
from app.backtest.metrics import summarize
from app.backtest.settle import settle_predictions, settle_row
from app.data.mlb import MlbClient

BASE = "https://statsapi.mlb.com"


def _row(**kw):
    base = {
        "date": "2026-06-07",
        "pitcher": "Aaron Nola",
        "pitcher_id": "605400",
        "side": "over",
        "line": "5.5",
        "over_odds": "-110",
        "under_odds": "-110",
        "edge": "0.06",
        "expected_ks": "6.5",
        "bet": "True",
    }
    base.update(kw)
    return base


def test_settle_row_win_over():
    bet = settle_row(_row(side="over", line="5.5"), actual_ks=7)
    assert bet.result == "win"
    assert bet.profit_units == pytest.approx(0.909, abs=1e-3)  # -110 -> 0.909


def test_settle_row_loss_over():
    bet = settle_row(_row(side="over", line="5.5"), actual_ks=4)
    assert bet.result == "loss"
    assert bet.profit_units == -1.0


def test_settle_row_under_win():
    bet = settle_row(_row(side="under", line="5.5"), actual_ks=3)
    assert bet.result == "win"


def test_settle_row_push_on_integer_line():
    bet = settle_row(_row(side="over", line="6"), actual_ks=6)
    assert bet.result == "push"
    assert bet.profit_units == 0.0


def test_summarize_roi_and_hitrate():
    settled = [
        settle_row(_row(side="over", line="5.5"), 7),   # win
        settle_row(_row(side="over", line="5.5"), 4),   # loss
        settle_row(_row(side="under", line="5.5"), 3),  # win
    ]
    report = summarize(settled)
    assert report.n_bets == 3
    assert report.wins == 2 and report.losses == 1
    assert report.hit_rate == pytest.approx(2 / 3)
    # profit = 0.909 - 1 + 0.909 = 0.818 over 3 bets
    assert report.roi == pytest.approx(0.818 / 3, abs=1e-3)


def test_clv_positive_when_market_moves_to_us():
    # Bet over at +120 (cheap), market closes -130 (expensive) -> we got value.
    clv = clv_for_side("over", bet_over=120, bet_under=-140,
                       close_over=-130, close_under=110)
    assert clv > 0


def test_find_closing_matches_by_name_and_date():
    rows = [{"date": "2026-06-07", "pitcher": "Jose Ramirez", "line": "5.5"}]
    assert find_closing("José Ramírez", "2026-06-07", rows) is not None
    assert find_closing("José Ramírez", "2026-06-08", rows) is None


@respx.mock
def test_get_actual_strikeouts_from_gamelog():
    payload = {
        "stats": [
            {
                "splits": [
                    {"date": "2026-06-06", "stat": {"strikeOuts": 5}},
                    {"date": "2026-06-07", "stat": {"strikeOuts": 9}},
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/people/605400/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    assert client.get_actual_strikeouts(605400, "2026-06-07") == 9
    assert client.get_actual_strikeouts(605400, "2026-06-01") is None


def test_settle_predictions_end_to_end(tmp_path):
    # Write a small predictions CSV, settle it with a fake MLB client.
    path = tmp_path / "predictions.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(_row().keys()))
        w.writeheader()
        w.writerow(_row(pitcher_id="1", side="over", line="5.5"))
        w.writerow(_row(pitcher_id="2", side="under", line="6.5"))

    class FakeMlb:
        def get_actual_strikeouts(self, pid, date, game_pk=None):
            return {1: 8, 2: 4}[pid]  # pitcher 1 over hits, pitcher 2 under hits

    settled = settle_predictions(str(path), mlb=FakeMlb())
    report = summarize(settled)
    assert report.n_bets == 2
    assert report.wins == 2
    assert report.roi is not None and report.roi > 0
