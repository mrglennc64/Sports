import csv

from app.config import Settings
from app.data.mlb import PitcherSeason, Start
from app.data.odds import OddsEvent, PropLine
from app.log.predictions import log_predictions
from app.pipeline import build_slate


class FakeMlb:
    def __init__(self):
        self._starts = [
            Start(1, 100, "José Ramírez", 111, "Boston Red Sox", "Fenway Park"),
            Start(1, 200, "No Prop Guy", 147, "New York Yankees", "Fenway Park"),
        ]

    def get_starts(self, date):
        return self._starts

    def get_pitcher_season(self, pid):
        return PitcherSeason(
            k_per_9=11.0, innings_per_start=6.0, games_started=20, innings_pitched=120.0
        )

    def get_team_k_rate(self, team_id):
        return 0.27  # high-K lineup


class FakeOdds:
    def list_events(self):
        return [OddsEvent("e1", "Boston Red Sox", "Away", "2026-06-07T00:00:00Z")]

    def get_strikeout_props(self, event_id):
        # Book is generous on the under; model should find over edge or vice versa.
        return [
            PropLine("Jose Ramirez", line=6.5, over_odds=-110, under_odds=-110,
                     bookmaker="draftkings")
        ]


def test_build_slate_matches_and_evaluates():
    slate = build_slate("2026-06-07", mlb=FakeMlb(), provider=FakeOdds(),
                        settings=Settings())
    ok = [r for r in slate.rows if r.status == "ok"]
    no_prop = [r for r in slate.rows if r.status == "no_prop"]

    assert len(ok) == 1
    assert len(no_prop) == 1  # "No Prop Guy" had no matching prop

    row = ok[0]
    assert row.pitcher == "José Ramírez"  # matched across accent difference
    assert row.line == 6.5
    assert row.expected_ks is not None
    assert row.side in ("over", "under")
    # model_prob and de-vigged fair_prob both present; edge is their difference
    assert abs((row.model_prob - row.fair_prob) - row.edge) < 1e-3


def test_predictions_log_roundtrip(tmp_path):
    slate = build_slate("2026-06-07", mlb=FakeMlb(), provider=FakeOdds(),
                        settings=Settings())
    ok = [r.__dict__ for r in slate.rows if r.status == "ok"]
    path = tmp_path / "predictions.csv"
    log_predictions(ok, str(path))

    with open(path, encoding="utf-8") as f:
        logged = list(csv.DictReader(f))
    assert len(logged) == 1
    assert logged[0]["pitcher"] == "José Ramírez"
    assert "logged_at" in logged[0]
