"""Client for the free MLB Stats API (statsapi.mlb.com). No API key required.

Provides the three pulls the pipeline needs:
  * today's scheduled starts (probable pitcher + opponent + venue)
  * a pitcher's season K/9 and innings-per-start
  * an opponent team's strikeout rate (K per plate appearance)
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE_URL = "https://statsapi.mlb.com"


@dataclass
class Start:
    """One probable-pitcher start within a game."""

    game_pk: int
    pitcher_id: int
    pitcher_name: str
    opponent_team_id: int
    opponent_team_name: str
    venue_name: str


# A starter realistically averages 3-7 innings; IP/GS outside this is an artefact of
# relief appearances polluting the season line, so we clamp the projection.
MIN_IP_PER_START = 3.0
MAX_IP_PER_START = 7.0


@dataclass
class PitcherSeason:
    k_per_9: float
    innings_per_start: float
    games_started: int
    innings_pitched: float


def _is_start(split: dict) -> bool:
    """True if this game-log split is a STARTED appearance (not relief)."""
    gs = split.get("stat", {}).get("gamesStarted")
    return str(gs) in ("1", "1.0")


def _select_gamelog_split(splits: list, date: str, game_pk: int | str | None = None) -> dict | None:
    """Pick the right game-log split for a starter prop (pure; unit-tested).

    * ``game_pk`` given  -> the split for that exact game (None if not found).
    * doubleheader (two splits on the date) without ``game_pk`` -> the single
      *started* split; if that's still ambiguous, None (don't misgrade).
    * relief-only appearance -> None (a starter prop is never graded on a relief line).
    """
    on_date = [s for s in splits if s.get("date") == date]
    if game_pk is not None:
        for s in on_date:
            if str(s.get("game", {}).get("gamePk")) == str(game_pk):
                return s
        return None
    starts = [s for s in on_date if _is_start(s)]
    if len(starts) == 1:
        return starts[0]
    if not starts and len(on_date) == 1 and "gamesStarted" not in on_date[0].get("stat", {}):
        return on_date[0]  # single appearance, no start flag available -> accept
    return None  # ambiguous doubleheader (need game_pk) or relief-only


def parse_innings(ip: str | float) -> float:
    """MLB reports innings like '120.1' meaning 120 and 1/3 innings.

    The fractional digit is thirds of an inning (.0/.1/.2), not a decimal.
    """
    s = str(ip)
    if "." not in s:
        return float(s)
    whole, frac = s.split(".", 1)
    thirds = int(frac[0]) if frac else 0
    return int(whole) + thirds / 3.0


class MlbClient:
    def __init__(self, client: httpx.Client | None = None, base_url: str = BASE_URL):
        self._client = client or httpx.Client(base_url=base_url, timeout=15.0)

    # --- schedule -------------------------------------------------------------
    def get_starts(self, date: str) -> list[Start]:
        """Return every probable-pitcher start for the given YYYY-MM-DD date."""
        resp = self._client.get(
            "/api/v1/schedule",
            params={
                "sportId": 1,
                "date": date,
                "hydrate": "probablePitcher,venue",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        starts: list[Start] = []
        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                starts.extend(self._starts_from_game(game))
        return starts

    @staticmethod
    def _starts_from_game(game: dict) -> list[Start]:
        game_pk = game.get("gamePk")
        venue_name = (game.get("venue") or {}).get("name", "")
        teams = game.get("teams", {})
        away = teams.get("away", {})
        home = teams.get("home", {})

        out: list[Start] = []
        # away pitcher faces the home lineup, and vice versa
        for side, opp in ((away, home), (home, away)):
            pitcher = side.get("probablePitcher")
            opp_team = opp.get("team", {})
            if not pitcher or not opp_team:
                continue
            out.append(
                Start(
                    game_pk=game_pk,
                    pitcher_id=pitcher.get("id"),
                    pitcher_name=pitcher.get("fullName", ""),
                    opponent_team_id=opp_team.get("id"),
                    opponent_team_name=opp_team.get("name", ""),
                    venue_name=venue_name,
                )
            )
        return out

    # --- pitcher season stats -------------------------------------------------
    def get_pitcher_season(self, pitcher_id: int) -> PitcherSeason | None:
        resp = self._client.get(
            f"/api/v1/people/{pitcher_id}/stats",
            params={"stats": "season", "group": "pitching"},
        )
        resp.raise_for_status()
        stat = _first_split_stat(resp.json())
        if not stat:
            return None

        gs = stat.get("gamesStarted") or 0
        ip = parse_innings(stat.get("inningsPitched", "0"))
        if not gs or ip <= 0:
            return None

        # The MLB feed uses 'strikeoutsPer9Inn' (lowercase o); an older 'strikeOutsPer9Inn'
        # alias exists but is frequently null. Fall back to computing it directly.
        k9 = stat.get("strikeoutsPer9Inn") or stat.get("strikeOutsPer9Inn")
        if k9 is None:
            ks = stat.get("strikeOuts")
            if ks is None:
                return None
            k9 = ks / ip * 9.0

        ip_per_start = min(MAX_IP_PER_START, max(MIN_IP_PER_START, ip / gs))
        return PitcherSeason(
            k_per_9=float(k9),
            innings_per_start=ip_per_start,
            games_started=int(gs),
            innings_pitched=ip,
        )

    # --- actual result (for backtesting) -------------------------------------
    def get_actual_strikeouts(
        self, pitcher_id: int, date: str, game_pk: int | str | None = None
    ) -> int | None:
        """Strikeouts the pitcher recorded on ``date`` (YYYY-MM-DD) in the STARTED game.

        Pass ``game_pk`` to grade the exact game — essential on doubleheaders, where
        the pitcher's team plays two games on one date and a date-only match would
        grade the wrong one. Without a ``game_pk`` we disambiguate by the started
        appearance (relief outings are never graded as a start). Returns None if the
        start can't be identified unambiguously (so a bad match is reported as
        unmatched, not silently misgraded).
        """
        resp = self._client.get(
            f"/api/v1/people/{pitcher_id}/stats",
            params={"stats": "gameLog", "group": "pitching"},
        )
        resp.raise_for_status()
        stats = resp.json().get("stats") or []
        if not stats:
            return None
        split = _select_gamelog_split(stats[0].get("splits", []), date, game_pk)
        if split is None:
            return None
        ks = split.get("stat", {}).get("strikeOuts")
        return int(ks) if ks is not None else None

    # --- opponent strikeout rate ---------------------------------------------
    def get_team_k_rate(self, team_id: int) -> float | None:
        resp = self._client.get(
            f"/api/v1/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting"},
        )
        resp.raise_for_status()
        stat = _first_split_stat(resp.json())
        if not stat:
            return None
        pa = stat.get("plateAppearances") or 0
        ks = stat.get("strikeOuts") or 0
        if not pa:
            return None
        return ks / pa


def _first_split_stat(payload: dict) -> dict | None:
    """Drill into the MLB stats envelope: stats[0].splits[0].stat."""
    stats = payload.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits") or []
    if not splits:
        return None
    return splits[0].get("stat")
