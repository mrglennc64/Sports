import httpx
import pytest
import respx

from app.data.mlb import MlbClient, parse_innings
from app.data.park import park_factor

BASE = "https://statsapi.mlb.com"


def test_parse_innings_thirds():
    assert parse_innings("120.0") == pytest.approx(120.0)
    assert parse_innings("120.1") == pytest.approx(120 + 1 / 3)
    assert parse_innings("120.2") == pytest.approx(120 + 2 / 3)
    assert parse_innings(95) == pytest.approx(95.0)


def test_park_factor_known_and_fallback():
    assert park_factor("Coors Field") == pytest.approx(0.95)
    assert park_factor("Nonexistent Park") == 1.0
    assert park_factor(None) == 1.0


@respx.mock
def test_get_starts_parses_both_pitchers():
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 777,
                        "venue": {"id": 3, "name": "Fenway Park"},
                        "teams": {
                            "away": {
                                "team": {"id": 147, "name": "New York Yankees"},
                                "probablePitcher": {"id": 1, "fullName": "Away Ace"},
                            },
                            "home": {
                                "team": {"id": 111, "name": "Boston Red Sox"},
                                "probablePitcher": {"id": 2, "fullName": "Home Ace"},
                            },
                        },
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(200, json=schedule)
    )

    client = MlbClient(client=httpx.Client(base_url=BASE))
    starts = client.get_starts("2025-07-01")

    assert len(starts) == 2
    away = next(s for s in starts if s.pitcher_id == 1)
    assert away.pitcher_name == "Away Ace"
    assert away.opponent_team_name == "Boston Red Sox"  # away pitcher faces home
    assert away.venue_name == "Fenway Park"


@respx.mock
def test_get_starts_skips_missing_probable():
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 1,
                        "venue": {"name": "Somewhere"},
                        "teams": {
                            "away": {"team": {"id": 1, "name": "A"}},  # no probable
                            "home": {
                                "team": {"id": 2, "name": "B"},
                                "probablePitcher": {"id": 9, "fullName": "Only Ace"},
                            },
                        },
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(200, json=schedule)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    starts = client.get_starts("2025-07-01")
    assert len(starts) == 1
    assert starts[0].pitcher_id == 9


@respx.mock
def test_get_pitcher_season():
    payload = {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "strikeoutsPer9Inn": 10.50,  # note: lowercase 'o'
                            "inningsPitched": "120.0",
                            "gamesStarted": 20,
                        }
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/people/543/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    season = client.get_pitcher_season(543)
    assert season.k_per_9 == pytest.approx(10.5)
    assert season.innings_per_start == pytest.approx(6.0)  # 120 / 20
    assert season.games_started == 20


@respx.mock
def test_innings_per_start_clamped_for_spot_starter():
    # 31.1 IP over 2 starts = 15.7 IP/start (relief-polluted) -> clamped to 7.0.
    payload = {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "strikeoutsPer9Inn": 9.5,
                            "inningsPitched": "31.1",
                            "gamesStarted": 2,
                        }
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/people/77/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    season = client.get_pitcher_season(77)
    assert season.innings_per_start == pytest.approx(7.0)  # clamped, not 15.7


@respx.mock
def test_get_pitcher_season_computes_k9_when_field_missing():
    # No per-9 field at all -> compute from strikeOuts / IP * 9.
    payload = {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "strikeOuts": 64,
                            "inningsPitched": "61.2",  # 61 and 2/3
                            "gamesStarted": 12,
                        }
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/people/9/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    season = client.get_pitcher_season(9)
    ip = 61 + 2 / 3
    assert season.k_per_9 == pytest.approx(64 / ip * 9.0)


@respx.mock
def test_get_team_k_rate():
    payload = {
        "stats": [{"splits": [{"stat": {"strikeOuts": 1350, "plateAppearances": 6000}}]}]
    }
    respx.get(f"{BASE}/api/v1/teams/111/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MlbClient(client=httpx.Client(base_url=BASE))
    assert client.get_team_k_rate(111) == pytest.approx(0.225)
