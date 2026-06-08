"""Tests for the daily line-snapshot script (app.data.snapshot)."""

from __future__ import annotations

import asyncio

import httpx
import respx

from app.data.client import StatsApiClient
from app.data.history import load_lines_csv
from app.data.odds import OddsEvent, OddsProvider, PropLine
from app.data.snapshot import snapshot_lines

BASE = "https://statsapi.mlb.com"


def _run(coro):
    return asyncio.run(coro)


def _client() -> StatsApiClient:
    return StatsApiClient(client=httpx.AsyncClient(base_url=BASE))


def _schedule():
    return {
        "dates": [{"games": [{
            "gamePk": 777,
            "venue": {"name": "Fenway Park"},
            "teams": {
                "away": {
                    "team": {"id": 147, "name": "New York Yankees"},
                    "probablePitcher": {"id": 543037, "fullName": "Gerrit Cole", "pitchHand": {"code": "R"}},
                },
                "home": {
                    "team": {"id": 111, "name": "Boston Red Sox"},
                    "probablePitcher": {"id": 605483, "fullName": "Brayan Bello", "pitchHand": {"code": "R"}},
                },
            },
        }]}]
    }


class FakeProvider(OddsProvider):
    """Returns one event with two strikeout props (one name-spelled differently)."""

    def list_events(self) -> list[OddsEvent]:
        return [OddsEvent(event_id="e1", home_team="Red Sox", away_team="Yankees", commence_time="")]

    def get_strikeout_props(self, event_id: str) -> list[PropLine]:
        return [
            PropLine("Gerrit Cole", 6.5, -115, -105, "draftkings"),
            PropLine("Brayan Bello", 5.5, -110, -110, "fanduel"),
        ]


def _mock_schedule():
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(200, json=_schedule())
    )


@respx.mock
def test_snapshot_writes_pitcher_ids_and_lines(tmp_path):
    _mock_schedule()
    path = str(tmp_path / "lines.csv")

    n = _run(snapshot_lines("2025-06-07", path, client=_client(), provider=FakeProvider()))
    assert n == 2

    # Stored by MLB pitcher id, so it round-trips through the history loader.
    lines = load_lines_csv(path)
    assert lines[("2025-06-07", 543037)] == 6.5
    assert lines[("2025-06-07", 605483)] == 5.5


@respx.mock
def test_snapshot_is_idempotent_for_same_date(tmp_path):
    _mock_schedule()
    path = str(tmp_path / "lines.csv")

    first = _run(snapshot_lines("2025-06-07", path, client=_client(), provider=FakeProvider()))
    second = _run(snapshot_lines("2025-06-07", path, client=_client(), provider=FakeProvider()))
    assert first == 2
    assert second == 0  # nothing new -> no duplicate rows

    # Exactly two data rows remain.
    with open(path, encoding="utf-8") as fh:
        data_rows = [ln for ln in fh.read().splitlines()[1:] if ln.strip()]
    assert len(data_rows) == 2


@respx.mock
def test_snapshot_falls_back_to_name_when_no_probable_match(tmp_path):
    _mock_schedule()
    path = str(tmp_path / "lines.csv")

    class StrangerProvider(OddsProvider):
        def list_events(self):
            return [OddsEvent("e1", "", "", "")]

        def get_strikeout_props(self, event_id):
            return [PropLine("Unknown Starter", 4.5, -120, +100, "betmgm")]

    n = _run(snapshot_lines("2025-06-07", path, client=_client(), provider=StrangerProvider()))
    assert n == 1
    # No probable-start match -> stored by name; history loader keys it by name.
    lines = load_lines_csv(path)
    assert lines[("2025-06-07", "Unknown Starter")] == 4.5


@respx.mock
def test_snapshot_appends_new_dates(tmp_path):
    _mock_schedule()
    path = str(tmp_path / "lines.csv")

    _run(snapshot_lines("2025-06-07", path, client=_client(), provider=FakeProvider()))
    n2 = _run(snapshot_lines("2025-06-08", path, client=_client(), provider=FakeProvider()))
    assert n2 == 2

    lines = load_lines_csv(path)
    assert ("2025-06-07", 543037) in lines
    assert ("2025-06-08", 543037) in lines
