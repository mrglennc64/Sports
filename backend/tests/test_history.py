"""Tests for the historical backtest loader (app.data.history).

All HTTP is mocked with ``respx`` — no live network. Async loaders are driven
via ``asyncio.run`` (pytest-asyncio is not installed; mirrors test_data.py).

Coverage:
  * GameOutcomes carry the correct actual_ks (read from the gameLog by date).
  * Starts with no final result on that date are skipped.
  * recent_start_ks is rebuilt from games strictly BEFORE on_date (no leakage).
  * User-supplied lines attach (by name and by id), CSV parsing works.
  * A loaded dataset flows into run_backtest and produces metrics.
"""

import asyncio
import textwrap

import httpx
import pytest
import respx

from app.data.client import StatsApiClient
from app.data.history import (
    _bullpen_from_ip,
    backtest_range,
    load_history_for_date,
    load_history_range,
    load_lines_csv,
)
from app.model.backtest import GameOutcome, run_backtest

BASE = "https://statsapi.mlb.com"


def _run(coro):
    return asyncio.run(coro)


def _client() -> StatsApiClient:
    return StatsApiClient(client=httpx.AsyncClient(base_url=BASE))


# --------------------------------------------------------------------------- #
# Shared mock payloads
# --------------------------------------------------------------------------- #
def _schedule_two_starts():
    """One game, two probable pitchers (ids 1 away, 2 home)."""
    return {
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
                                    "pitchHand": {"code": "R"},
                                },
                            },
                            "home": {
                                "team": {"id": 111, "name": "Boston Red Sox"},
                                "probablePitcher": {
                                    "id": 2,
                                    "fullName": "Home Ace",
                                    "pitchHand": {"code": "L"},
                                },
                            },
                        },
                    }
                ]
            }
        ]
    }


def _gamelog(pitcher_id, ks_on_target, target="2025-06-07", final=True):
    """gameLog with three prior starts and (optionally) one on the target date.

    Prior starts (oldest-first) precede the target so recent_start_ks can be
    verified as strictly-before-target.
    """
    splits = [
        {"date": "2025-05-20", "stat": {"strikeOuts": 5, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-05-26", "stat": {"strikeOuts": 7, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-06-01", "stat": {"strikeOuts": 9, "gamesStarted": 1, "inningsPitched": "7.0"}},
    ]
    if final:
        splits.append(
            {"date": target, "stat": {"strikeOuts": ks_on_target, "gamesStarted": 1, "inningsPitched": "6.0"}}
        )
    return {"people": [{"id": pitcher_id, "stats": [{"splits": splits}]}]}


def _opponent_payloads():
    """statSplits vr/vl + byDateRange windows for any team id."""
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
    window = {"stats": [{"splits": [{"stat": {"strikeOuts": 100, "plateAppearances": 400}}]}]}
    return splits, window


def _workload_payload():
    return {"stats": [{"splits": [{"stat": {"inningsPitched": "120.0", "gamesStarted": 20}}]}]}


def _mock_all(*, p1_ks=8, p2_ks=10, p1_final=True, p2_final=True):
    """Wire up schedule + per-pitcher gameLog/workload + opponent/lineup routes."""
    splits, window = _opponent_payloads()

    def schedule_router(request):
        # lineup-strength calls pass gamePk; probable-starts call passes date.
        if request.url.params.get("gamePk"):
            # no lineup posted -> force team fallback
            return httpx.Response(
                200,
                json={"dates": [{"games": [{"gamePk": 777, "lineups": {"homePlayers": [], "awayPlayers": []}}]}]},
            )
        return httpx.Response(200, json=_schedule_two_starts())

    respx.get(f"{BASE}/api/v1/schedule").mock(side_effect=schedule_router)

    # Pitcher gameLogs (hydrate route, no /stats suffix).
    respx.get(f"{BASE}/api/v1/people/1", params__contains={"hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"}).mock(
        return_value=httpx.Response(200, json=_gamelog(1, p1_ks, final=p1_final))
    )
    respx.get(f"{BASE}/api/v1/people/2", params__contains={"hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"}).mock(
        return_value=httpx.Response(200, json=_gamelog(2, p2_ks, final=p2_final))
    )

    # Pitcher workload (/stats season).
    respx.get(f"{BASE}/api/v1/people/1/stats").mock(
        return_value=httpx.Response(200, json=_workload_payload())
    )
    respx.get(f"{BASE}/api/v1/people/2/stats").mock(
        return_value=httpx.Response(200, json=_workload_payload())
    )

    # Opponent team stats (statSplits + byDateRange) for both teams.
    def team_router(request):
        if request.url.params.get("stats") == "statSplits":
            return httpx.Response(200, json=splits)
        return httpx.Response(200, json=window)

    respx.get(f"{BASE}/api/v1/teams/111/stats").mock(side_effect=team_router)
    respx.get(f"{BASE}/api/v1/teams/147/stats").mock(side_effect=team_router)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@respx.mock
def test_load_history_for_date_builds_outcomes_with_actual_ks():
    _mock_all(p1_ks=8, p2_ks=10)
    outcomes = _run(load_history_for_date(_client(), "2025-06-07"))

    assert len(outcomes) == 2
    assert all(isinstance(o, GameOutcome) for o in outcomes)
    by_name = {o.inputs.pitcher_name: o for o in outcomes}
    assert by_name["Away Ace"].actual_ks == 8
    assert by_name["Home Ace"].actual_ks == 10
    # no lines supplied -> all None
    assert all(o.line is None for o in outcomes)


@respx.mock
def test_recent_start_ks_excludes_on_date_and_after():
    _mock_all(p1_ks=8, p2_ks=10)
    outcomes = _run(load_history_for_date(_client(), "2025-06-07"))
    away = next(o for o in outcomes if o.inputs.pitcher_name == "Away Ace")
    # Only the three starts BEFORE 2025-06-07, most-recent-first.
    # The 8-K target-date start must NOT leak into recent form.
    assert away.inputs.pitcher_form.recent_start_ks == [9, 7, 5]
    assert 8 not in away.inputs.pitcher_form.recent_start_ks


@respx.mock
def test_starts_without_final_result_are_skipped():
    # p2 has no gameLog entry for the date (game not final) -> skipped.
    _mock_all(p1_ks=6, p2_final=False)
    outcomes = _run(load_history_for_date(_client(), "2025-06-07"))
    assert len(outcomes) == 1
    assert outcomes[0].inputs.pitcher_name == "Away Ace"
    assert outcomes[0].actual_ks == 6


@respx.mock
def test_lines_attach_by_name_and_by_id():
    _mock_all(p1_ks=8, p2_ks=10)
    lines = {
        ("2025-06-07", "away ace"): 6.5,  # name, case-insensitive
        ("2025-06-07", 2): 7.5,           # id
    }
    outcomes = _run(load_history_for_date(_client(), "2025-06-07", lines=lines))
    by_name = {o.inputs.pitcher_name: o for o in outcomes}
    assert by_name["Away Ace"].line == 6.5
    assert by_name["Home Ace"].line == 7.5


@respx.mock
def test_load_history_range_inclusive():
    # Same fixtures answer both dates; gameLog has a 06-07 final, none for 06-08,
    # so only 06-07 yields outcomes (2 starts) -> range still returns those.
    _mock_all(p1_ks=8, p2_ks=10)
    outcomes = _run(load_history_range(_client(), "2025-06-07", "2025-06-08"))
    # 06-07 -> 2 finals; 06-08 -> no gameLog entry on that date -> skipped.
    assert len(outcomes) == 2


@respx.mock
def test_dataset_flows_into_run_backtest():
    _mock_all(p1_ks=8, p2_ks=10)
    lines = {("2025-06-07", 1): 6.5, ("2025-06-07", 2): 9.5}
    outcomes = _run(load_history_for_date(_client(), "2025-06-07", lines=lines))
    result = run_backtest(outcomes)
    assert result.accuracy.n == 2
    assert result.accuracy.mae >= 0
    # both records carry a line -> betting metrics present
    assert result.betting is not None
    assert result.betting.n_plays >= 0


@respx.mock
def test_backtest_range_convenience():
    _mock_all(p1_ks=8, p2_ks=10)
    result, tuned = _run(backtest_range(_client(), "2025-06-07", "2025-06-07"))
    assert result.accuracy.n == 2
    assert tuned is None  # tune defaults off


def test_load_lines_csv(tmp_path):
    csv_text = textwrap.dedent(
        """\
        date,pitcher,line,over_odds,under_odds
        2025-06-07,Away Ace,6.5,-110,-110
        2025-06-07,2,7.5,-115,-105
        2025-06-07,Bad Row,,,
        """
    )
    path = tmp_path / "lines.csv"
    path.write_text(csv_text, encoding="utf-8")

    lines = load_lines_csv(str(path))
    assert lines[("2025-06-07", "Away Ace")] == 6.5
    assert lines[("2025-06-07", 2)] == 7.5  # numeric pitcher -> int id key
    # row with empty line is skipped
    assert ("2025-06-07", "Bad Row") not in lines


# --------------------------------------------------------------------------- #
# Point-in-time (as-of) guarantees
# --------------------------------------------------------------------------- #
@respx.mock
def test_workload_and_k9_come_from_gamelog_not_season_stats():
    """As-of workload/K9 are derived from the gameLog, not the season /stats call."""
    _mock_all(p1_ks=8, p2_ks=10)
    outcomes = _run(load_history_for_date(_client(), "2025-06-07"))
    away = next(o for o in outcomes if o.inputs.pitcher_name == "Away Ace")

    # gameLog prior to 06-07: starts of 6.0, 6.0, 7.0 IP -> 19 IP / 3 GS = 6.33.
    assert away.inputs.workload.expected_innings == pytest.approx(19 / 3)
    # K/9 over the prior 30 days: (5+7+9) K / 19 IP * 9.
    assert away.inputs.pitcher_form.k_per_9_last_30 == pytest.approx(21 / 19 * 9)
    # The season pitching /stats endpoint must NOT be used for workload anymore.
    assert not any(
        c.request.url.path == "/api/v1/people/1/stats" for c in respx.calls
    )


def test_bullpen_leash_neutral_on_thin_sample():
    # Fewer than MIN_APPEARANCES_FOR_LEASH prior starts -> trust nothing.
    bp = _bullpen_from_ip(raw_ip_per_start=1.5, games_started=2)
    assert bp.is_opener is False
    assert bp.leash_factor == 1.0


def test_bullpen_detects_opener_from_low_ip():
    # An established 1.5 IP/start role over enough starts -> opener, deep cut.
    bp = _bullpen_from_ip(raw_ip_per_start=1.5, games_started=8)
    assert bp.is_opener is True
    assert bp.leash_factor < 0.5


def test_bullpen_neutral_for_full_starter():
    bp = _bullpen_from_ip(raw_ip_per_start=6.1, games_started=12)
    assert bp.is_opener is False
    assert bp.leash_factor == 1.0  # capped: never inflates a workhorse


def test_bullpen_short_leash_between_opener_and_full():
    bp = _bullpen_from_ip(raw_ip_per_start=4.4, games_started=10)
    assert bp.is_opener is False
    assert 0.7 < bp.leash_factor < 0.9


@respx.mock
def test_opponent_windows_end_the_day_before_on_date():
    """byDateRange opponent windows must exclude the game date itself."""
    _mock_all(p1_ks=8, p2_ks=10)
    _run(load_history_for_date(_client(), "2025-06-07"))

    end_dates = {
        c.request.url.params.get("endDate")
        for c in respx.calls
        if c.request.url.params.get("stats") == "byDateRange"
        and "/teams/" in c.request.url.path
    }
    # Every as-of window ends 2025-06-06, never on the game date.
    assert end_dates == {"2025-06-06"}


@respx.mock
def test_asof_lineup_uses_opponent_players_and_windowed_stats():
    """Posted lineup -> as-of per-hitter K% over the opponent's (correct) side."""
    def schedule_router(request):
        if request.url.params.get("gamePk"):
            # Away pitcher (id 1) faces the HOME lineup -> homePlayers are the opp.
            return httpx.Response(
                200,
                json={"dates": [{"games": [{
                    "gamePk": 777,
                    "lineups": {
                        "homePlayers": [{"id": 50}, {"id": 51}],   # opponent (correct)
                        "awayPlayers": [{"id": 90}, {"id": 91}],   # pitcher's own team
                    },
                }]}]},
            )
        return httpx.Response(200, json=_schedule_two_starts())

    respx.get(f"{BASE}/api/v1/schedule").mock(side_effect=schedule_router)
    respx.get(f"{BASE}/api/v1/people/1", params__contains={"hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"}).mock(
        return_value=httpx.Response(200, json=_gamelog(1, 8))
    )
    # Home pitcher has no final result so only the away pitcher's start is built.
    respx.get(f"{BASE}/api/v1/people/2", params__contains={"hydrate": "stats(group=[pitching],type=[gameLog],season=2025)"}).mock(
        return_value=httpx.Response(200, json=_gamelog(2, 0, final=False))
    )

    splits, window = _opponent_payloads()

    def team_router(request):
        if request.url.params.get("stats") == "statSplits":
            return httpx.Response(200, json=splits)
        return httpx.Response(200, json=window)

    respx.get(f"{BASE}/api/v1/teams/111/stats").mock(side_effect=team_router)
    respx.get(f"{BASE}/api/v1/teams/147/stats").mock(side_effect=team_router)

    # Opponent (home) hitters 50/51 get a high as-of K%; own-team 90/91 would be low.
    def hitter_router(request):
        return httpx.Response(
            200,
            json={"stats": [{"splits": [{"stat": {"strikeOuts": 30, "plateAppearances": 100}}]}]},
        )

    own_called = []

    def own_router(request):
        own_called.append(request.url.path)
        return httpx.Response(
            200,
            json={"stats": [{"splits": [{"stat": {"strikeOuts": 1, "plateAppearances": 100}}]}]},
        )

    respx.get(f"{BASE}/api/v1/people/50/stats").mock(side_effect=hitter_router)
    respx.get(f"{BASE}/api/v1/people/51/stats").mock(side_effect=hitter_router)
    respx.get(f"{BASE}/api/v1/people/90/stats").mock(side_effect=own_router)
    respx.get(f"{BASE}/api/v1/people/91/stats").mock(side_effect=own_router)

    outcomes = _run(load_history_for_date(_client(), "2025-06-07"))
    away = next(o for o in outcomes if o.inputs.pitcher_name == "Away Ace")

    # K% comes from the OPPONENT'S hitters (30/100), not the pitcher's own team.
    assert away.inputs.lineup.projected_lineup_k_pct == pytest.approx(0.30)
    assert own_called == []  # the pitcher's own lineup was never queried
    # Per-hitter windows are as-of (end the day before the game).
    hitter_end_dates = {
        c.request.url.params.get("endDate")
        for c in respx.calls
        if "/people/50/stats" in c.request.url.path
    }
    assert hitter_end_dates == {"2025-06-06"}


@respx.mock
def test_csv_lines_attach_end_to_end(tmp_path):
    _mock_all(p1_ks=8, p2_ks=10)
    path = tmp_path / "lines.csv"
    path.write_text("date,pitcher,line\n2025-06-07,Away Ace,6.5\n", encoding="utf-8")
    lines = load_lines_csv(str(path))

    outcomes = _run(load_history_for_date(_client(), "2025-06-07", lines=lines))
    away = next(o for o in outcomes if o.inputs.pitcher_name == "Away Ace")
    home = next(o for o in outcomes if o.inputs.pitcher_name == "Home Ace")
    assert away.line == 6.5
    assert home.line is None
