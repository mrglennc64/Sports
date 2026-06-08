"""Tests for the MLB Stats data layer (app.data).

All HTTP is mocked with ``respx`` — no live network calls. JSON payloads mirror
the real statsapi.mlb.com shapes confirmed against the live API. Async fetchers
are driven via ``asyncio.run`` so no pytest-asyncio dependency is needed.
"""

import asyncio

import httpx
import pytest
import respx

from app.data.assemble import build_projection_inputs
from app.data.client import StatsApiClient
from app.data.mlb_stats import (
    fetch_lineup_strength,
    fetch_opponent_k_profile,
    fetch_pitcher_form,
    fetch_pitcher_workload,
    fetch_probable_starts,
    parse_innings,
)
from app.model.inputs import (
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
)

BASE = "https://statsapi.mlb.com"


def _run(coro):
    return asyncio.run(coro)


def _client() -> StatsApiClient:
    return StatsApiClient(client=httpx.AsyncClient(base_url=BASE))


# --- helpers -----------------------------------------------------------------


def test_parse_innings_thirds():
    assert parse_innings("120.0") == pytest.approx(120.0)
    assert parse_innings("61.2") == pytest.approx(61 + 2 / 3)
    assert parse_innings(95) == pytest.approx(95.0)


# --- schedule / probable pitchers --------------------------------------------


@respx.mock
def test_fetch_probable_starts_parses_both_pitchers():
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 777,
                        "venue": {"name": "Fenway Park"},
                        "teams": {
                            "away": {
                                "team": {"id": 147, "name": "New York Yankees"},
                                "probablePitcher": {
                                    "id": 1,
                                    "fullName": "Away Ace",
                                    "pitchHand": {"code": "L"},
                                },
                            },
                            "home": {
                                "team": {"id": 111, "name": "Boston Red Sox"},
                                "probablePitcher": {
                                    "id": 2,
                                    "fullName": "Home Ace",
                                    "pitchHand": {"code": "R"},
                                },
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

    starts = _run(fetch_probable_starts(_client(), "2025-06-07"))
    assert len(starts) == 2
    away = next(s for s in starts if s.pitcher_id == 1)
    assert away.pitcher_name == "Away Ace"
    assert away.throws is Handedness.L
    assert away.is_home is False
    assert away.opponent_team_name == "Boston Red Sox"  # away faces home
    assert away.venue_name == "Fenway Park"


@respx.mock
def test_fetch_probable_starts_skips_missing_probable():
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
                                "probablePitcher": {"id": 9, "fullName": "Only"},
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
    starts = _run(fetch_probable_starts(_client(), "2025-06-07"))
    assert len(starts) == 1
    assert starts[0].pitcher_id == 9
    assert starts[0].is_home is True


# --- pitcher recent form -----------------------------------------------------


def _gamelog_payload():
    # gameLog is oldest-first in the real API.
    splits = [
        {"date": "2025-04-01", "stat": {"strikeOuts": 5, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-05-20", "stat": {"strikeOuts": 7, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-05-26", "stat": {"strikeOuts": 9, "gamesStarted": 1, "inningsPitched": "7.0"}},
        {"date": "2025-06-01", "stat": {"strikeOuts": 6, "gamesStarted": 1, "inningsPitched": "5.0"}},
        {"date": "2025-06-07", "stat": {"strikeOuts": 8, "gamesStarted": 1, "inningsPitched": "6.0"}},
    ]
    return {"people": [{"id": 543, "stats": [{"splits": splits}]}]}


@respx.mock
def test_fetch_pitcher_form_recent_ks_and_k9():
    respx.get(f"{BASE}/api/v1/people/543").mock(
        return_value=httpx.Response(200, json=_gamelog_payload())
    )
    form = _run(fetch_pitcher_form(_client(), 543, Handedness.R, 2025))
    assert isinstance(form, PitcherRecentForm)
    # most-recent-first
    assert form.recent_start_ks == [8, 6, 9, 7, 5]
    # last 30 days from 2025-06-07 cutoff = 2025-05-08 -> the 4 May/Jun starts:
    # K = 7+9+6+8 = 30 over IP = 6+7+5+6 = 24 -> 30/24*9 = 11.25
    assert form.k_per_9_last_30 == pytest.approx(30 / 24 * 9.0)
    # free API gives neither of these
    assert form.swinging_strike_pct is None
    assert form.csw_pct is None


@respx.mock
def test_fetch_pitcher_form_empty_log():
    respx.get(f"{BASE}/api/v1/people/99").mock(
        return_value=httpx.Response(200, json={"people": [{"id": 99, "stats": []}]})
    )
    form = _run(fetch_pitcher_form(_client(), 99, Handedness.L, 2025))
    assert form.recent_start_ks == []
    assert form.k_per_9_last_30 == 0.0
    assert form.throws is Handedness.L


# --- pitcher workload --------------------------------------------------------


@respx.mock
def test_fetch_pitcher_workload():
    payload = {
        "stats": [
            {"splits": [{"stat": {"inningsPitched": "120.0", "gamesStarted": 20}}]}
        ]
    }
    respx.get(f"{BASE}/api/v1/people/543/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    wl = _run(fetch_pitcher_workload(_client(), 543, 2025))
    assert wl.expected_innings == pytest.approx(6.0)  # 120/20
    assert wl.expected_pitch_count == pytest.approx(6.0 * 16.0)
    assert wl.manager_hook_pitch_count > 0


@respx.mock
def test_fetch_pitcher_workload_clamped_spot_starter():
    payload = {
        "stats": [
            {"splits": [{"stat": {"inningsPitched": "31.1", "gamesStarted": 2}}]}
        ]
    }
    respx.get(f"{BASE}/api/v1/people/77/stats").mock(
        return_value=httpx.Response(200, json=payload)
    )
    wl = _run(fetch_pitcher_workload(_client(), 77, 2025))
    assert wl.expected_innings == pytest.approx(7.0)  # clamped, not 15.7


@respx.mock
def test_fetch_pitcher_workload_missing_data_neutral():
    respx.get(f"{BASE}/api/v1/people/5/stats").mock(
        return_value=httpx.Response(200, json={"stats": []})
    )
    wl = _run(fetch_pitcher_workload(_client(), 5, 2025))
    assert wl.expected_innings == pytest.approx(5.0)  # neutral midpoint of 3-7


# --- opponent K profile ------------------------------------------------------


def _mock_opponent(team_id: int):
    splits = {
        "stats": [
            {
                "splits": [
                    {"split": {"code": "vl"}, "stat": {"strikeOuts": 400, "plateAppearances": 1697}},
                    {"split": {"code": "vr"}, "stat": {"strikeOuts": 1063, "plateAppearances": 4538}},
                ]
            }
        ]
    }
    window14 = {"stats": [{"splits": [{"stat": {"strikeOuts": 100, "plateAppearances": 400}}]}]}
    window30 = {"stats": [{"splits": [{"stat": {"strikeOuts": 220, "plateAppearances": 1000}}]}]}

    def router(request):
        stats = request.url.params.get("stats")
        if stats == "statSplits":
            return httpx.Response(200, json=splits)
        start = request.url.params.get("startDate")
        # 14-day window has the later startDate
        if start and start >= "2025-05-24":
            return httpx.Response(200, json=window14)
        return httpx.Response(200, json=window30)

    respx.get(f"{BASE}/api/v1/teams/{team_id}/stats").mock(side_effect=router)


@respx.mock
def test_fetch_opponent_k_profile():
    _mock_opponent(111)
    prof = _run(fetch_opponent_k_profile(_client(), 111, 2025, today="2025-06-07"))
    assert isinstance(prof, OpponentKProfile)
    assert prof.k_pct_vs_rhp == pytest.approx(1063 / 4538)
    assert prof.k_pct_vs_lhp == pytest.approx(400 / 1697)
    assert prof.k_pct_last_14 == pytest.approx(100 / 400)
    assert prof.k_pct_last_30 == pytest.approx(220 / 1000)
    # no lineup supplied -> starting falls back to last-14
    assert prof.k_pct_starting_lineup == pytest.approx(100 / 400)


@respx.mock
def test_fetch_opponent_k_profile_uses_lineup_when_given():
    _mock_opponent(111)
    prof = _run(
        fetch_opponent_k_profile(
            _client(), 111, 2025, today="2025-06-07", lineup_k_pct=0.31
        )
    )
    assert prof.k_pct_starting_lineup == pytest.approx(0.31)


@respx.mock
def test_fetch_opponent_k_profile_all_missing_falls_back():
    empty = {"stats": []}
    respx.get(f"{BASE}/api/v1/teams/200/stats").mock(
        return_value=httpx.Response(200, json=empty)
    )
    prof = _run(fetch_opponent_k_profile(_client(), 200, 2025, today="2025-06-07"))
    # every field defaults to the ~league-average fallback, all in [0,1]
    assert 0 < prof.k_pct_vs_rhp <= 1
    assert prof.k_pct_last_30 == pytest.approx(prof.k_pct_vs_rhp)


# --- lineup strength ---------------------------------------------------------


@respx.mock
def test_fetch_lineup_strength_averages_posted_nine():
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 555,
                        "lineups": {
                            "awayPlayers": [{"id": 10}, {"id": 11}],
                            "homePlayers": [{"id": 20}, {"id": 21}],
                        },
                    }
                ]
            }
        ]
    }
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(200, json=schedule)
    )

    def hitter(ks, pa):
        return {"stats": [{"splits": [{"stat": {"strikeOuts": ks, "plateAppearances": pa}}]}]}

    respx.get(f"{BASE}/api/v1/people/20/stats").mock(
        return_value=httpx.Response(200, json=hitter(60, 200))
    )
    respx.get(f"{BASE}/api/v1/people/21/stats").mock(
        return_value=httpx.Response(200, json=hitter(40, 200))
    )

    # opponent is home -> homePlayers (20, 21)
    ls = _run(fetch_lineup_strength(_client(), 555, opponent_is_home=True, season=2025))
    assert isinstance(ls, LineupStrength)
    # PA-weighted: (60+40)/(200+200) = 0.25
    assert ls.projected_lineup_k_pct == pytest.approx(0.25)


@respx.mock
def test_fetch_lineup_strength_none_when_not_posted():
    schedule = {"dates": [{"games": [{"gamePk": 555, "lineups": {"homePlayers": [], "awayPlayers": []}}]}]}
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(200, json=schedule)
    )
    ls = _run(fetch_lineup_strength(_client(), 555, opponent_is_home=False, season=2025))
    assert ls is None


# --- end-to-end assembly -----------------------------------------------------


@respx.mock
def test_build_projection_inputs_full_shape():
    from app.data.mlb_stats import ProbableStart

    start = ProbableStart(
        game_pk=555,
        pitcher_id=543,
        pitcher_name="Test Ace",
        throws=Handedness.R,
        is_home=False,  # opponent is home
        opponent_team_id=111,
        opponent_team_name="Boston Red Sox",
        venue_name="Fenway Park",
    )

    # pitcher form (gameLog) + workload (season)
    respx.get(f"{BASE}/api/v1/people/543", params__contains={"hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"}).mock(
        return_value=httpx.Response(200, json=_gamelog_payload())
    )
    respx.get(f"{BASE}/api/v1/people/543/stats").mock(
        return_value=httpx.Response(
            200,
            json={"stats": [{"splits": [{"stat": {"inningsPitched": "120.0", "gamesStarted": 20}}]}]},
        )
    )
    # lineup schedule -> no lineup posted, force team fallback
    respx.get(f"{BASE}/api/v1/schedule").mock(
        return_value=httpx.Response(
            200,
            json={"dates": [{"games": [{"gamePk": 555, "lineups": {"homePlayers": [], "awayPlayers": []}}]}]},
        )
    )
    _mock_opponent(111)

    inputs = _run(build_projection_inputs(_client(), start, "2025-06-07"))
    assert isinstance(inputs, ProjectionInputs)
    assert inputs.pitcher_name == "Test Ace"
    assert inputs.pitcher_form.throws is Handedness.R
    assert inputs.opponent.k_pct_vs_rhp == pytest.approx(1063 / 4538)
    assert inputs.workload.expected_innings == pytest.approx(6.0)
    # lineup not posted -> falls back to opponent starting (last-14) rate
    assert inputs.lineup.projected_lineup_k_pct == pytest.approx(100 / 400)
    # free-API limitations
    assert inputs.umpire is None
    assert inputs.pitch_mix is None
