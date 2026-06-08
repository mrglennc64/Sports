"""Home-plate umpire strike-zone tendencies.

The MLB Stats API tells us *who* is behind the plate (via the game boxscore
``officials``), but NOT how that umpire's zone affects strikeouts. Those
tendencies come from a separate public source (e.g. Umpire Scorecards,
umpscorecards.com). This module:

  1. fetches the assigned home-plate umpire for a game, and
  2. looks the umpire up in a small, replaceable table of K tendencies,

so the projection's umpire factor uses a real zone tendency when we have data
and falls back to neutral (``None``) when we don't.

Table format (JSON), keyed by umpire full name::

    {
      "Doug Eddings": {"k_rate": 0.235, "called_strike_rate": 0.51},
      ...
    }

where ``k_rate`` is strikeouts per plate appearance in that umpire's games
(league average is ~0.22). Populate it from a trusted source; any umpire not
in the table returns ``None`` and the model treats that factor as neutral.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.data.client import StatsApiClient
from app.model.inputs import UmpireProfile

UmpireTable = dict[str, UmpireProfile]


def load_umpire_table(path: str | Path) -> UmpireTable:
    """Load the umpire K-tendency table from JSON. Missing file -> empty table.

    Keys are normalised to lowercase for case-insensitive lookup. A top-level
    ``"_comment"`` key (used for documentation in the file) is ignored.
    """
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    table: UmpireTable = {}
    for name, vals in raw.items():
        if name.startswith("_") or not isinstance(vals, dict):
            continue
        k_rate = vals.get("k_rate")
        if k_rate is None:
            continue
        table[name.strip().lower()] = UmpireProfile(
            historical_k_rate=float(k_rate),
            called_strike_rate=vals.get("called_strike_rate"),
        )
    return table


def umpire_profile(name: str | None, table: UmpireTable) -> UmpireProfile | None:
    """Look up an umpire's tendency by name (case-insensitive). None if unknown."""
    if not name:
        return None
    return table.get(name.strip().lower())


async def fetch_home_plate_umpire(
    client: StatsApiClient, game_pk: int
) -> str | None:
    """Full name of the assigned home-plate umpire, or None if not yet posted.

    Crews are typically known close to game time, so early in the day this may
    return None (the model then treats the umpire factor as neutral).
    """
    payload = await client.get_json(f"/api/v1/game/{game_pk}/boxscore")
    for official in payload.get("officials") or []:
        if official.get("officialType") == "Home Plate":
            return (official.get("official") or {}).get("fullName")
    return None


async def fetch_umpire_profile(
    client: StatsApiClient, game_pk: int, table: UmpireTable
) -> UmpireProfile | None:
    """Assigned HP umpire's K tendency for a game, or None if unknown/unposted."""
    name = await fetch_home_plate_umpire(client, game_pk)
    return umpire_profile(name, table)
