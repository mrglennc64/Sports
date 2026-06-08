"""Tests for the Baseball Savant data layer (app.data.savant).

All HTTP is mocked with ``respx`` — no live network. CSV bodies mirror the real
baseballsavant.mlb.com shapes confirmed against the live endpoints (UTF-8 BOM,
a quoted ``"last_name, first_name"`` header with an embedded comma, percents in
0-100). Async fetchers are driven via ``asyncio.run`` so no pytest-asyncio
dependency is needed.
"""

import asyncio

import httpx
import pytest
import respx

from app.data.assemble import build_projection_inputs
from app.data.client import StatsApiClient
from app.data.mlb_stats import ProbableStart
from app.data.savant import (
    SavantClient,
    compute_whiff_csw,
    fetch_pitch_mix_matchup,
    fetch_pitcher_whiff_csw,
    parse_pitcher_arsenal,
    parse_team_whiff_by_pitch,
)
from app.model.inputs import (
    Handedness,
    PitchMixMatchup,
    ProjectionInputs,
)

SAVANT = "https://baseballsavant.mlb.com"
STATS = "https://statsapi.mlb.com"
BOM = "﻿"


def _run(coro):
    return asyncio.run(coro)


def _savant() -> SavantClient:
    return SavantClient(client=httpx.AsyncClient(base_url=SAVANT))


def _stats() -> StatsApiClient:
    return StatsApiClient(client=httpx.AsyncClient(base_url=STATS))


# --- statcast description CSV (swinging-strike% / CSW%) -----------------------


def _statcast_csv(descriptions: list[str]) -> str:
    """A minimal statcast 'details' CSV with the columns we read."""
    header = '"pitch_type","description","type"'
    lines = [header]
    for d in descriptions:
        lines.append(f'"FF","{d}","S"')
    return BOM + "\n".join(lines) + "\n"


def test_compute_whiff_csw_basic():
    # 2 whiffs + 1 foul_tip (whiff) = 3 whiffs, 2 called strikes, 5 other -> 10 pitches
    descs = [
        "swinging_strike",
        "swinging_strike_blocked",
        "foul_tip",
        "called_strike",
        "called_strike",
        "ball",
        "ball",
        "foul",
        "hit_into_play",
        "ball",
    ]
    swstr, csw = compute_whiff_csw([{"description": d} for d in descs])
    assert swstr == pytest.approx(3 / 10)
    assert csw == pytest.approx((3 + 2) / 10)


def test_compute_whiff_csw_empty_is_none():
    assert compute_whiff_csw([]) == (None, None)
    # rows with no usable description -> still neutral
    assert compute_whiff_csw([{"description": ""}]) == (None, None)


@respx.mock
def test_fetch_pitcher_whiff_csw_parses_csv():
    descs = ["swinging_strike"] * 3 + ["called_strike"] * 2 + ["ball"] * 5
    respx.get(f"{SAVANT}/statcast_search/csv").mock(
        return_value=httpx.Response(200, text=_statcast_csv(descs))
    )
    swstr, csw = _run(fetch_pitcher_whiff_csw(_savant(), 656302, 2024))
    assert swstr == pytest.approx(3 / 10)
    assert csw == pytest.approx(5 / 10)


@respx.mock
def test_fetch_pitcher_whiff_csw_http_error_neutral():
    respx.get(f"{SAVANT}/statcast_search/csv").mock(
        return_value=httpx.Response(500)
    )
    assert _run(fetch_pitcher_whiff_csw(_savant(), 1, 2024)) == (None, None)


@respx.mock
def test_fetch_pitcher_whiff_csw_empty_body_neutral():
    respx.get(f"{SAVANT}/statcast_search/csv").mock(
        return_value=httpx.Response(200, text="")
    )
    assert _run(fetch_pitcher_whiff_csw(_savant(), 1, 2024)) == (None, None)


# --- pitch-arsenal CSV parsing ----------------------------------------------

# Header reproduces the real quirk: first field is the quoted "last_name,
# first_name" (one column containing a comma).
_ARSENAL_HEADER = (
    '"last_name, first_name","player_id","team_name_alt","pitch_type",'
    '"pitch_name","pitches","pitch_usage","whiff_percent","k_percent"'
)


def _pitcher_arsenal_csv() -> str:
    rows = [
        _ARSENAL_HEADER,
        '"Cease, Dylan",656302,"SD","FF","4-Seam Fastball","1500",55,18.0,20.0',
        '"Cease, Dylan",656302,"SD","SL","Slider","1000",37,44.0,39.0',
        '"Cease, Dylan",656302,"SD","CH","Changeup","200",8,30.0,15.0',
        # a different pitcher that must be ignored
        '"Other, Guy",111111,"LAD","FF","4-Seam Fastball","900",60,10.0,9.0',
    ]
    return BOM + "\n".join(rows) + "\n"


def _opponent_batter_arsenal_csv() -> str:
    # Two BOS batters; team whiff% is a pitches-weighted mean per pitch type.
    rows = [
        _ARSENAL_HEADER,
        '"Duran, Jarren",680776,"BOS","FF","4-Seam Fastball","1000",20.0,20.0,18.0',
        '"Devers, Rafael",646240,"BOS","FF","4-Seam Fastball","1000",30.0,30.0,22.0',
        '"Duran, Jarren",680776,"BOS","SL","Slider","500",40.0,40.0,30.0',
        '"Devers, Rafael",646240,"BOS","SL","Slider","500",40.0,40.0,30.0',
        # opponent never sees a changeup column here -> CH must be skipped in matchup
    ]
    return BOM + "\n".join(rows) + "\n"


def test_parse_pitcher_arsenal_usage_fractions():
    from app.data.savant import _parse_csv

    usage = parse_pitcher_arsenal(_parse_csv(_pitcher_arsenal_csv()), 656302)
    assert usage == {
        "FF": pytest.approx(0.55),
        "SL": pytest.approx(0.37),
        "CH": pytest.approx(0.08),
    }
    # other pitcher's rows excluded
    assert "FC" not in usage


def test_parse_team_whiff_weighted_mean():
    from app.data.savant import _parse_csv

    whiff = parse_team_whiff_by_pitch(_parse_csv(_opponent_batter_arsenal_csv()))
    # FF: (20*1000 + 30*1000)/2000 = 25.0% -> 0.25
    assert whiff["FF"] == pytest.approx(0.25)
    # SL: (40*500 + 40*500)/1000 = 40.0% -> 0.40
    assert whiff["SL"] == pytest.approx(0.40)


# --- pitch-mix matchup -------------------------------------------------------


@respx.mock
def test_fetch_pitch_mix_matchup_joins_usage_and_opp_whiff():
    def router(request):
        typ = request.url.params.get("type")
        if typ == "pitcher":
            return httpx.Response(200, text=_pitcher_arsenal_csv())
        return httpx.Response(200, text=_opponent_batter_arsenal_csv())

    respx.get(f"{SAVANT}/leaderboard/pitch-arsenal-stats").mock(side_effect=router)

    mix = _run(fetch_pitch_mix_matchup(_savant(), 656302, "BOS", 2024))
    assert isinstance(mix, PitchMixMatchup)
    by_type = {p.pitch_type: p for p in mix.pitches}
    # CH dropped: opponent has no CH whiff data -> never fabricated
    assert set(by_type) == {"FF", "SL"}
    assert by_type["FF"].usage_pct == pytest.approx(0.55)
    assert by_type["FF"].opponent_whiff_pct == pytest.approx(0.25)
    assert by_type["SL"].usage_pct == pytest.approx(0.37)
    assert by_type["SL"].opponent_whiff_pct == pytest.approx(0.40)
    # sorted most-used first
    assert mix.pitches[0].pitch_type == "FF"


@respx.mock
def test_fetch_pitch_mix_matchup_http_error_empty():
    respx.get(f"{SAVANT}/leaderboard/pitch-arsenal-stats").mock(
        return_value=httpx.Response(503)
    )
    mix = _run(fetch_pitch_mix_matchup(_savant(), 656302, "BOS", 2024))
    assert mix.pitches == []


# --- assemble wiring ---------------------------------------------------------


def _wire_stats_for_start():
    """Mock the MLB Stats calls build_projection_inputs makes (no Savant)."""
    gamelog = {
        "people": [
            {
                "id": 543,
                "stats": [
                    {
                        "splits": [
                            {
                                "date": "2025-06-07",
                                "stat": {
                                    "strikeOuts": 8,
                                    "gamesStarted": 1,
                                    "inningsPitched": "6.0",
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }
    respx.get(
        f"{STATS}/api/v1/people/543",
        params__contains={
            "hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"
        },
    ).mock(return_value=httpx.Response(200, json=gamelog))
    respx.get(f"{STATS}/api/v1/people/543/stats").mock(
        return_value=httpx.Response(
            200,
            json={
                "stats": [
                    {"splits": [{"stat": {"inningsPitched": "120.0", "gamesStarted": 20}}]}
                ]
            },
        )
    )
    respx.get(f"{STATS}/api/v1/schedule").mock(
        return_value=httpx.Response(
            200,
            json={
                "dates": [
                    {
                        "games": [
                            {
                                "gamePk": 555,
                                "lineups": {"homePlayers": [], "awayPlayers": []},
                            }
                        ]
                    }
                ]
            },
        )
    )
    # opponent team stats: empty -> league-average fallback (don't care here)
    respx.get(f"{STATS}/api/v1/teams/111/stats").mock(
        return_value=httpx.Response(200, json={"stats": []})
    )


def _start() -> ProbableStart:
    return ProbableStart(
        game_pk=555,
        pitcher_id=543,
        pitcher_name="Test Ace",
        throws=Handedness.R,
        is_home=False,
        opponent_team_id=111,
        opponent_team_name="Boston Red Sox",
        venue_name="Fenway Park",
    )


@respx.mock
def test_build_projection_inputs_without_savant_leaves_factors_none():
    _wire_stats_for_start()
    inputs = _run(build_projection_inputs(_stats(), _start(), "2025-06-07"))
    assert isinstance(inputs, ProjectionInputs)
    assert inputs.pitcher_form.swinging_strike_pct is None
    assert inputs.pitcher_form.csw_pct is None
    assert inputs.pitch_mix is None


@respx.mock
def test_build_projection_inputs_with_savant_fills_factors():
    _wire_stats_for_start()
    # team-abbrev lookup
    respx.get(f"{STATS}/api/v1/teams/111").mock(
        return_value=httpx.Response(
            200, json={"teams": [{"id": 111, "abbreviation": "BOS"}]}
        )
    )

    # Savant: pitcher whiff/csw + arsenal matchup. Pitcher id 543 here.
    descs = ["swinging_strike"] * 3 + ["called_strike"] * 2 + ["ball"] * 5
    respx.get(f"{SAVANT}/statcast_search/csv").mock(
        return_value=httpx.Response(200, text=_statcast_csv(descs))
    )

    pitcher_csv = (
        BOM
        + "\n".join(
            [
                _ARSENAL_HEADER,
                '"Test, Ace",543,"SD","FF","4-Seam Fastball","1500",60,18.0,20.0',
                '"Test, Ace",543,"SD","SL","Slider","1000",40,44.0,39.0',
            ]
        )
        + "\n"
    )

    def arsenal_router(request):
        if request.url.params.get("type") == "pitcher":
            return httpx.Response(200, text=pitcher_csv)
        return httpx.Response(200, text=_opponent_batter_arsenal_csv())

    respx.get(f"{SAVANT}/leaderboard/pitch-arsenal-stats").mock(
        side_effect=arsenal_router
    )

    inputs = _run(
        build_projection_inputs(
            _stats(), _start(), "2025-06-07", savant=_savant()
        )
    )
    assert inputs.pitcher_form.swinging_strike_pct == pytest.approx(0.3)
    assert inputs.pitcher_form.csw_pct == pytest.approx(0.5)
    assert inputs.pitch_mix is not None
    by_type = {p.pitch_type: p for p in inputs.pitch_mix.pitches}
    assert by_type["FF"].usage_pct == pytest.approx(0.60)
    assert by_type["FF"].opponent_whiff_pct == pytest.approx(0.25)
    assert by_type["SL"].opponent_whiff_pct == pytest.approx(0.40)
