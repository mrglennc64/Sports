"""Baseball Savant fetchers for the 2 projection factors the free MLB Stats
API cannot provide.

The free MLB Stats API (:mod:`app.data.mlb_stats`) covers 5 of the 7 projection
factors. The remaining two require Statcast data, which Baseball Savant exposes
publicly (read-only, no key) via CSV leaderboard / search endpoints:

  6. Pitcher swinging-strike % and CSW% (Called Strikes + Whiffs)
  7. Pitch-mix matchup: pitcher usage by pitch type joined with the OPPONENT
     team's whiff% against each pitch type.

Confirmed endpoints + columns (probed live against baseballsavant.mlb.com):

  * Pitch-arsenal leaderboard (per-pitch usage + whiff%), CSV::

        GET /leaderboard/pitch-arsenal-stats?type={pitcher|batter}&year=YYYY
            &team=ABBR&min=N&csv=true

    Columns used: ``player_id``, ``team_name_alt`` (team abbrev), ``pitch_type``
    (FF/SL/CH/...), ``pitches`` (count), ``pitch_usage`` (percent 0-100),
    ``whiff_percent`` (whiffs/swings, percent 0-100). NOTE the first CSV column
    header is the single quoted field ``"last_name, first_name"`` (an embedded
    comma), and the body is UTF-8 with a BOM — so we decode ``utf-8-sig`` and
    parse with :mod:`csv` (which honours the quoting).

  * Statcast search (raw pitch-level descriptions), CSV::

        GET /statcast_search/csv?all=true&type=details&player_type=pitcher
            &hfSea=YYYY|&pitchers_lookup[]=PID

    Columns used: ``description``. Swinging-strike% and CSW% are computed from
    the per-pitch ``description`` counts (the only public source that yields a
    correct *whiffs/pitches* and *called+whiffs/pitches*, since the arsenal
    leaderboard's ``whiff_percent`` is whiffs/**swings**, not whiffs/pitches).

      swinging-strike% = whiffs / total_pitches
      CSW%             = (called_strikes + whiffs) / total_pitches

    where "whiffs" = swinging_strike + swinging_strike_blocked + foul_tip
    + missed_bunt.

All rates are returned as fractions in [0, 1] to match :mod:`app.model.inputs`.
Anything missing returns ``None`` / an empty matchup so the model degrades to
neutral — we never fabricate numbers.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict

import httpx

from app.model.inputs import PitchMixMatchup, PitchUsage

BASE_URL = "https://baseballsavant.mlb.com"
DEFAULT_TIMEOUT = 15.0

# Pitch ``description`` values (statcast) that count as a whiff (swing & miss).
_WHIFF_DESCRIPTIONS = frozenset(
    {
        "swinging_strike",
        "swinging_strike_blocked",
        "foul_tip",
        "missed_bunt",
    }
)
_CALLED_STRIKE_DESCRIPTIONS = frozenset({"called_strike"})


class SavantClient:
    """Async GET-only client for Baseball Savant CSV endpoints.

    Mirrors :class:`app.data.client.StatsApiClient` so it can be injected /
    mocked (e.g. via ``respx``) without touching the network. Returns response
    text; callers parse the CSV themselves.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout, follow_redirects=True
        )

    async def get_text(self, path: str, params: dict | None = None) -> str:
        """GET ``path`` and return the response body text, raising on HTTP errors."""
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.text

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> SavantClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


# --- CSV helpers -------------------------------------------------------------


def _parse_csv(text: str) -> list[dict[str, str]]:
    """Parse a Savant CSV body (UTF-8 BOM, quoted fields) into dict rows."""
    if not text or not text.strip():
        return []
    # Savant bodies start with a BOM; utf-8-sig strips it. The text we already
    # hold is decoded, so just drop a leading BOM char if present.
    if text and text[0] == "﻿":
        text = text[1:]
    return list(csv.DictReader(io.StringIO(text)))


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int:
    f = _to_float(value)
    return int(f) if f is not None else 0


# --- pitcher swinging-strike % / CSW% ----------------------------------------


def compute_whiff_csw(rows: list[dict[str, str]]) -> tuple[float | None, float | None]:
    """Compute (swinging_strike_pct, csw_pct) from statcast ``description`` rows.

    Returns ``(None, None)`` when there are no pitches (so the model stays
    neutral). Rates are fractions in [0, 1].
    """
    total = 0
    whiffs = 0
    called = 0
    for row in rows:
        desc = (row.get("description") or "").strip()
        if not desc:
            continue
        total += 1
        if desc in _WHIFF_DESCRIPTIONS:
            whiffs += 1
        elif desc in _CALLED_STRIKE_DESCRIPTIONS:
            called += 1
    if total <= 0:
        return None, None
    swstr = whiffs / total
    csw = (called + whiffs) / total
    return swstr, csw


async def fetch_pitcher_whiff_csw(
    client: SavantClient,
    pitcher_id: int,
    season: int,
) -> tuple[float | None, float | None]:
    """Pitcher swinging-strike% and CSW% for a season from Statcast pitch data.

    Pulls the pitcher's per-pitch ``description`` log and aggregates. Any error
    or empty result degrades to ``(None, None)`` so the projection stays neutral
    — we never fabricate numbers.
    """
    try:
        text = await client.get_text(
            "/statcast_search/csv",
            params={
                "all": "true",
                "type": "details",
                "player_type": "pitcher",
                "hfSea": f"{season}|",
                "pitchers_lookup[]": pitcher_id,
            },
        )
    except httpx.HTTPError:
        return None, None
    rows = _parse_csv(text)
    return compute_whiff_csw(rows)


# --- pitch-mix matchup -------------------------------------------------------


def parse_pitcher_arsenal(
    rows: list[dict[str, str]], pitcher_id: int
) -> dict[str, float]:
    """Map pitch_type -> usage fraction [0,1] for one pitcher from arsenal rows.

    ``pitch_usage`` is a percent (0-100) in the CSV; converted to a fraction.
    Rows for other pitchers are ignored.
    """
    usage: dict[str, float] = {}
    pid = str(pitcher_id)
    for row in rows:
        if (row.get("player_id") or "").strip() != pid:
            continue
        pitch = (row.get("pitch_type") or "").strip()
        pct = _to_float(row.get("pitch_usage"))
        if not pitch or pct is None:
            continue
        usage[pitch] = pct / 100.0
    return usage


def parse_team_whiff_by_pitch(rows: list[dict[str, str]]) -> dict[str, float]:
    """Map pitch_type -> team whiff fraction [0,1] from batter arsenal rows.

    The batter arsenal CSV is per-batter; we aggregate to a team-level whiff%
    per pitch type by weighting each batter's ``whiff_percent`` by the number of
    ``pitches`` they saw of that type (a pitches-weighted mean).
    """
    weighted: dict[str, float] = defaultdict(float)
    weights: dict[str, float] = defaultdict(float)
    for row in rows:
        pitch = (row.get("pitch_type") or "").strip()
        whiff = _to_float(row.get("whiff_percent"))
        pitches = _to_int(row.get("pitches"))
        if not pitch or whiff is None or pitches <= 0:
            continue
        weighted[pitch] += whiff * pitches
        weights[pitch] += pitches
    return {
        pitch: (weighted[pitch] / weights[pitch]) / 100.0
        for pitch in weighted
        if weights[pitch] > 0
    }


async def fetch_pitch_mix_matchup(
    client: SavantClient,
    pitcher_id: int,
    opponent_team_abbr: str,
    season: int,
    min_pitches: int = 1,
) -> PitchMixMatchup:
    """Pitcher pitch usage joined with the OPPONENT team's whiff% per pitch type.

    ``opponent_team_abbr`` is the Savant team abbreviation (e.g. ``"BOS"``).
    Returns an empty :class:`PitchMixMatchup` (neutral) on any error or when no
    pitch types can be joined — we never fabricate numbers.
    """
    try:
        pitcher_text = await client.get_text(
            "/leaderboard/pitch-arsenal-stats",
            params={
                "type": "pitcher",
                "year": season,
                "min": min_pitches,
                "csv": "true",
            },
        )
        batter_text = await client.get_text(
            "/leaderboard/pitch-arsenal-stats",
            params={
                "type": "batter",
                "year": season,
                "team": opponent_team_abbr,
                "min": min_pitches,
                "csv": "true",
            },
        )
    except httpx.HTTPError:
        return PitchMixMatchup(pitches=[])

    usage = parse_pitcher_arsenal(_parse_csv(pitcher_text), pitcher_id)
    opp_whiff = parse_team_whiff_by_pitch(_parse_csv(batter_text))

    pitches: list[PitchUsage] = []
    for pitch_type, usage_pct in usage.items():
        whiff = opp_whiff.get(pitch_type)
        if whiff is None:
            # No opponent whiff data for this pitch type: skip rather than guess.
            continue
        pitches.append(
            PitchUsage(
                pitch_type=pitch_type,
                usage_pct=min(1.0, max(0.0, usage_pct)),
                opponent_whiff_pct=min(1.0, max(0.0, whiff)),
            )
        )
    # Most-used pitch first for stable, readable output.
    pitches.sort(key=lambda p: p.usage_pct, reverse=True)
    return PitchMixMatchup(pitches=pitches)
