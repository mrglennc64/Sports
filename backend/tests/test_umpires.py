"""Tests for the home-plate umpire data layer."""

from __future__ import annotations

import asyncio
import json

import httpx
import respx

from app.data.client import StatsApiClient
from app.data.umpires import (
    fetch_home_plate_umpire,
    fetch_umpire_profile,
    load_umpire_table,
    umpire_profile,
)

BASE = "https://statsapi.mlb.com"


def write_table(tmp_path):
    p = tmp_path / "umpires.json"
    p.write_text(
        json.dumps(
            {
                "_comment": "ignored",
                "_league_average_k_rate": 0.22,
                "Pat Hoberg": {"k_rate": 0.235, "called_strike_rate": 0.52},
                "Bad Row": {"called_strike_rate": 0.5},  # no k_rate -> skipped
            }
        ),
        encoding="utf-8",
    )
    return p


def test_load_table_skips_comments_and_incomplete_rows(tmp_path):
    table = load_umpire_table(write_table(tmp_path))
    assert set(table.keys()) == {"pat hoberg"}
    assert table["pat hoberg"].historical_k_rate == 0.235


def test_load_missing_file_returns_empty():
    assert load_umpire_table("definitely/not/here.json") == {}


def test_lookup_is_case_insensitive_and_handles_unknown(tmp_path):
    table = load_umpire_table(write_table(tmp_path))
    assert umpire_profile("PAT HOBERG", table) is not None
    assert umpire_profile("  pat hoberg ", table) is not None
    assert umpire_profile("Unknown Ump", table) is None
    assert umpire_profile(None, table) is None


@respx.mock
def test_fetch_home_plate_umpire_parses_officials():
    respx.get(f"{BASE}/api/v1/game/777609/boxscore").mock(
        return_value=httpx.Response(
            200,
            json={
                "officials": [
                    {"officialType": "First Base", "official": {"fullName": "Derek Thomas"}},
                    {"officialType": "Home Plate", "official": {"fullName": "Doug Eddings"}},
                ]
            },
        )
    )

    async def run():
        async with StatsApiClient() as client:
            return await fetch_home_plate_umpire(client, 777609)

    assert asyncio.run(run()) == "Doug Eddings"


@respx.mock
def test_fetch_umpire_profile_combines_assignment_and_table():
    respx.get(f"{BASE}/api/v1/game/123/boxscore").mock(
        return_value=httpx.Response(
            200,
            json={
                "officials": [
                    {"officialType": "Home Plate", "official": {"fullName": "Pat Hoberg"}}
                ]
            },
        )
    )
    from app.model.inputs import UmpireProfile

    table = {"pat hoberg": UmpireProfile(historical_k_rate=0.235)}

    async def run():
        async with StatsApiClient() as client:
            return await fetch_umpire_profile(client, 123, table)

    profile = asyncio.run(run())
    assert profile is not None
    assert profile.historical_k_rate == 0.235


@respx.mock
def test_fetch_umpire_profile_none_when_not_posted():
    respx.get(f"{BASE}/api/v1/game/999/boxscore").mock(
        return_value=httpx.Response(200, json={"officials": []})
    )

    async def run():
        async with StatsApiClient() as client:
            return await fetch_umpire_profile(client, 999, {"x": None})

    assert asyncio.run(run()) is None
