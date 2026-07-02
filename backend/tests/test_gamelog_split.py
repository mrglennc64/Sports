"""Tests for game-log split selection (grading integrity: doubleheaders + relief)."""
from __future__ import annotations

from app.data.mlb import _select_gamelog_split


def _split(date, gp, gs, ks):
    return {"date": date, "game": {"gamePk": gp}, "stat": {"gamesStarted": gs, "strikeOuts": ks}}


def test_single_start_on_date():
    splits = [_split("2026-07-01", 111, 1, 8)]
    assert _select_gamelog_split(splits, "2026-07-01")["stat"]["strikeOuts"] == 8


def test_game_pk_disambiguates_doubleheader():
    # two games same date; only game_pk can pick the right one
    splits = [_split("2026-07-01", 111, 1, 8), _split("2026-07-01", 222, 1, 3)]
    assert _select_gamelog_split(splits, "2026-07-01", game_pk=222)["stat"]["strikeOuts"] == 3
    assert _select_gamelog_split(splits, "2026-07-01", game_pk=111)["stat"]["strikeOuts"] == 8


def test_game_pk_not_found_returns_none():
    splits = [_split("2026-07-01", 111, 1, 8)]
    assert _select_gamelog_split(splits, "2026-07-01", game_pk=999) is None


def test_relief_appearance_is_not_graded_as_a_start():
    splits = [_split("2026-07-01", 111, 0, 2)]   # gamesStarted=0 -> relief
    assert _select_gamelog_split(splits, "2026-07-01") is None


def test_ambiguous_doubleheader_without_game_pk_returns_none():
    # both started (extremely rare, but must not misgrade) -> can't pick -> None
    splits = [_split("2026-07-01", 111, 1, 8), _split("2026-07-01", 222, 1, 3)]
    assert _select_gamelog_split(splits, "2026-07-01") is None


def test_started_split_chosen_over_relief_same_date():
    splits = [_split("2026-07-01", 111, 1, 8), _split("2026-07-01", 222, 0, 1)]
    assert _select_gamelog_split(splits, "2026-07-01")["stat"]["strikeOuts"] == 8


def test_single_appearance_without_start_flag_is_accepted():
    splits = [{"date": "2026-07-01", "game": {"gamePk": 111}, "stat": {"strikeOuts": 5}}]
    assert _select_gamelog_split(splits, "2026-07-01")["stat"]["strikeOuts"] == 5
