"""Fetch + parse the free MLB Stats API into the model's input shapes.

Coverage vs. the 7 projection factors (see ``app.model.inputs``):

  Covered by this free-API layer (5 of 7):
    1. Opponent K% vs RHP/LHP        -> statSplits sitCodes vr/vl
    2. Opponent K% last 14d / 30d    -> byDateRange windows
    3. Pitcher recent form (Ks/K9)   -> pitching gameLog
    4. Expected workload (innings)   -> season IP / games started
    5. Tonight's lineup K%           -> schedule ``lineups`` hydration

  NOT available from the MLB Stats API (need Baseball Savant later, 2 of 7):
    6. Swinging-strike % / CSW%      -> left as ``None`` (model degrades to neutral)
    7. Pitch-mix vs opponent whiff%  -> ``pitch_mix`` left ``None``

Umpire data is also outside this API, so ``umpire`` is left ``None``.

Rates are returned as fractions in [0, 1]: K% = strikeOuts / plateAppearances.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.data.client import StatsApiClient
from app.model.inputs import (
    BullpenContext,
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
)

# A starter realistically averages 3-7 IP; values outside this come from relief
# appearances polluting the season line, so we clamp the workload projection.
MIN_IP_PER_START = 3.0
MAX_IP_PER_START = 7.0
# Bullpen / opener leash knobs (mirror app.data.history; the clamp above hides
# the sub-3-IP opener signal, so the leash is derived from RAW IP/start).
NORMAL_START_IP = 5.5
OPENER_IP_THRESHOLD = 3.0
MIN_APPEARANCES_FOR_LEASH = 3

# Default pitch-count assumptions when we only know expected innings.
PITCHES_PER_INNING = 16.0
DEFAULT_HOOK_PITCH_COUNT = 100.0

DEFAULT_RECENT_STARTS = 5

# Recency blend for innings-per-start: weight recent 21-day window vs season average
# to catch mid-season fatigue/tightening leash that STD averages miss.
RECENT_WINDOW_DAYS = 21
RECENT_MIN_STARTS = 3  # minimum starts in window to trust the signal
RECENT_IP_START_WEIGHT = 0.6  # recent window gets 60% weight
SEASON_IP_START_WEIGHT = 0.4  # season average gets 40% weight


@dataclass
class ProbableStart:
    """One probable-pitcher start within a scheduled game."""

    game_pk: int
    pitcher_id: int
    pitcher_name: str
    throws: Handedness
    is_home: bool
    opponent_team_id: int
    opponent_team_name: str
    venue_name: str


# --- innings helper ----------------------------------------------------------


def parse_innings(ip: str | float) -> float:
    """Convert MLB innings ('120.1' = 120 and 1/3) to a true float.

    The fractional digit is thirds of an inning (.0/.1/.2), not a decimal.
    """
    s = str(ip)
    if "." not in s:
        return float(s)
    whole, frac = s.split(".", 1)
    thirds = int(frac[0]) if frac else 0
    return int(whole) + thirds / 3.0


def _handedness(code: str | None) -> Handedness:
    # Switch pitchers don't exist in practice; default unknown to R.
    return Handedness.L if code == "L" else Handedness.R


def _first_split_stat(payload: dict) -> dict | None:
    """Drill into the stats envelope: stats[0].splits[0].stat."""
    stats = payload.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits") or []
    if not splits:
        return None
    return splits[0].get("stat")


def _k_pct(stat: dict | None) -> float | None:
    if not stat:
        return None
    pa = stat.get("plateAppearances") or 0
    if not pa:
        return None
    ks = stat.get("strikeOuts") or 0
    return ks / pa


# --- schedule / probable pitchers --------------------------------------------


async def fetch_probable_starts(
    client: StatsApiClient, on_date: str
) -> list[ProbableStart]:
    """Every probable-pitcher start for ``on_date`` (YYYY-MM-DD)."""
    payload = await client.get_json(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "date": on_date,
            "hydrate": "probablePitcher,lineups,team",
        },
    )
    starts: list[ProbableStart] = []
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            starts.extend(_starts_from_game(game))
    return starts


def _starts_from_game(game: dict) -> list[ProbableStart]:
    game_pk = game.get("gamePk")
    venue_name = (game.get("venue") or {}).get("name", "")
    teams = game.get("teams", {})
    away = teams.get("away", {})
    home = teams.get("home", {})

    out: list[ProbableStart] = []
    # away pitcher faces the home lineup, and vice versa
    for side, opp, is_home in ((away, home, False), (home, away, True)):
        pitcher = side.get("probablePitcher")
        opp_team = opp.get("team", {})

        # Skip if opponent team missing (can't make predictions without opponent)
        if not opp_team:
            continue

        # Include game even if probable pitcher not announced (show as TBD)
        out.append(
            ProbableStart(
                game_pk=game_pk,
                pitcher_id=pitcher.get("id") if pitcher else None,
                pitcher_name=pitcher.get("fullName", "TBD") if pitcher else "TBD",
                throws=_handedness((pitcher.get("pitchHand") or {}).get("code")) if pitcher else None,
                is_home=is_home,
                opponent_team_id=opp_team.get("id"),
                opponent_team_name=opp_team.get("name", ""),
                venue_name=venue_name,
            )
        )
    return out


# --- pitcher recent form -----------------------------------------------------


async def fetch_pitcher_form(
    client: StatsApiClient,
    pitcher_id: int,
    throws: Handedness,
    season: int,
    recent_starts: int = DEFAULT_RECENT_STARTS,
) -> PitcherRecentForm:
    """Pitcher recent form from the season pitching gameLog.

    ``recent_start_ks`` is most-recent-first; ``k_per_9_last_30`` is computed
    over the last 30 calendar days of the log. swinging-strike % / CSW% are not
    in this API, so they stay ``None`` (the model treats that as neutral).
    """
    payload = await client.get_json(
        f"/api/v1/people/{pitcher_id}",
        params={
            "hydrate": f"stats(group=[pitching],type=[gameLog],season={season})"
        },
    )
    people = payload.get("people") or []
    splits: list[dict] = []
    if people:
        stats = people[0].get("stats") or []
        if stats:
            splits = stats[0].get("splits") or []

    # gameLog is oldest-first; restrict to actual starts, newest-first.
    starts = [s for s in splits if (s.get("stat") or {}).get("gamesStarted")]
    starts.reverse()

    recent_ks = [
        int(s["stat"]["strikeOuts"])
        for s in starts[:recent_starts]
        if s.get("stat", {}).get("strikeOuts") is not None
    ]

    k_per_9 = _k_per_9_last_30(splits)

    return PitcherRecentForm(
        throws=throws,
        recent_start_ks=recent_ks,
        k_per_9_last_30=k_per_9,
        swinging_strike_pct=None,
        csw_pct=None,
    )


def _k_per_9_last_30(splits: list[dict]) -> float:
    """K/9 over appearances in the last 30 days of the log (0.0 if none)."""
    if not splits:
        return 0.0
    dates = [s.get("date") for s in splits if s.get("date")]
    if not dates:
        return 0.0
    latest = max(date.fromisoformat(d) for d in dates)
    cutoff = latest - timedelta(days=30)

    total_k = 0
    total_ip = 0.0
    for s in splits:
        d = s.get("date")
        if not d or date.fromisoformat(d) < cutoff:
            continue
        stat = s.get("stat") or {}
        total_k += int(stat.get("strikeOuts") or 0)
        total_ip += parse_innings(stat.get("inningsPitched", "0"))
    if total_ip <= 0:
        return 0.0
    return total_k / total_ip * 9.0


# --- pitcher workload --------------------------------------------------------


async def _fetch_recent_ip_per_start(
    client: StatsApiClient,
    pitcher_id: int,
    season: int,
    end_date: date,
    window_days: int = RECENT_WINDOW_DAYS,
    min_starts: int = RECENT_MIN_STARTS,
) -> float | None:
    """Recent innings per start over the last N days, or None if insufficient sample.

    Returns the average IP/start over the trailing window. If the pitcher has fewer
    than min_starts in the window, returns None so the caller can fall back to
    season average. This catches mid-season fatigue and tightening leash patterns
    that season-to-date averages miss.
    """
    start_date = end_date - timedelta(days=window_days)
    payload = await client.get_json(
        f"/api/v1/people/{pitcher_id}/stats",
        params={
            "stats": "byDateRange",
            "group": "pitching",
            "season": season,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    )
    stat = _first_split_stat(payload)
    if not stat:
        return None
    gs = int(stat.get("gamesStarted") or 0)
    ip = parse_innings(stat.get("inningsPitched", "0"))
    if gs < min_starts or ip <= 0:
        return None
    return ip / gs


async def fetch_pitcher_workload(
    client: StatsApiClient, pitcher_id: int, season: int, today: date | None = None
) -> tuple[ExpectedWorkload, BullpenContext]:
    """Expected workload + bullpen leash from recency-blended IP / games started.

    Blends recent 21-day window (60%) with season average (40%) to catch mid-season
    fatigue and tightening leash patterns. Falls back to season average if the pitcher
    has fewer than 3 recent starts.

    ``expected_innings`` is clamped to 3-7 IP; the ``BullpenContext`` is read
    from the RAW (unclamped) IP/start so an opener or short-leash role — which
    the clamp would otherwise hide — still trims the strikeout ceiling.
    """
    today = today or date.today()

    # Fetch season-to-date workload
    payload = await client.get_json(
        f"/api/v1/people/{pitcher_id}/stats",
        params={"stats": "season", "group": "pitching", "season": season},
    )
    stat = _first_split_stat(payload)
    season_ip_per_start = (MIN_IP_PER_START + MAX_IP_PER_START) / 2  # neutral fallback
    gs = 0
    if stat:
        gs = int(stat.get("gamesStarted") or 0)
        ip = parse_innings(stat.get("inningsPitched", "0"))
        if gs and ip > 0:
            season_ip_per_start = ip / gs

    # Fetch recent window and blend if sufficient sample
    recent_ip_per_start = await _fetch_recent_ip_per_start(
        client, pitcher_id, season, today
    )
    if recent_ip_per_start is not None:
        raw_ip_per_start = (
            recent_ip_per_start * RECENT_IP_START_WEIGHT +
            season_ip_per_start * SEASON_IP_START_WEIGHT
        )
    else:
        raw_ip_per_start = season_ip_per_start

    ip_per_start = min(MAX_IP_PER_START, max(MIN_IP_PER_START, raw_ip_per_start))
    expected_pitches = ip_per_start * PITCHES_PER_INNING
    workload = ExpectedWorkload(
        expected_innings=ip_per_start,
        expected_pitch_count=expected_pitches,
        manager_hook_pitch_count=DEFAULT_HOOK_PITCH_COUNT,
    )

    if gs < MIN_APPEARANCES_FOR_LEASH:
        bullpen = BullpenContext(is_opener=False, leash_factor=1.0)
    else:
        leash = min(1.0, max(0.25, raw_ip_per_start / NORMAL_START_IP))
        bullpen = BullpenContext(
            is_opener=raw_ip_per_start < OPENER_IP_THRESHOLD, leash_factor=leash
        )
    return workload, bullpen


# --- opponent K profile ------------------------------------------------------


async def fetch_opponent_k_profile(
    client: StatsApiClient,
    team_id: int,
    season: int,
    today: str,
    lineup_k_pct: float | None = None,
) -> OpponentKProfile:
    """Opponent K% by handedness split and recent windows.

    ``lineup_k_pct`` (tonight's actual nine) is used for
    ``k_pct_starting_lineup`` when supplied; otherwise it falls back to the
    last-14-day team rate.
    """
    end = date.fromisoformat(today)
    k_vr, k_vl = await _fetch_splits_vr_vl(client, team_id, season)
    k14 = await _fetch_window_k_pct(
        client, team_id, season, end - timedelta(days=14), end
    )
    k30 = await _fetch_window_k_pct(
        client, team_id, season, end - timedelta(days=30), end
    )

    # Fall back across signals so we never crash on a missing split.
    base = k30 or k14 or k_vr or k_vl or 0.22  # ~league-average K% if all missing
    k_vr = k_vr if k_vr is not None else base
    k_vl = k_vl if k_vl is not None else base
    k14 = k14 if k14 is not None else base
    k30 = k30 if k30 is not None else base
    starting = lineup_k_pct if lineup_k_pct is not None else k14

    return OpponentKProfile(
        k_pct_vs_rhp=k_vr,
        k_pct_vs_lhp=k_vl,
        k_pct_last_14=k14,
        k_pct_last_30=k30,
        k_pct_starting_lineup=starting,
    )


async def _fetch_splits_vr_vl(
    client: StatsApiClient, team_id: int, season: int
) -> tuple[float | None, float | None]:
    payload = await client.get_json(
        f"/api/v1/teams/{team_id}/stats",
        params={
            "stats": "statSplits",
            "group": "hitting",
            "season": season,
            "sitCodes": "vr,vl",
        },
    )
    k_vr = k_vl = None
    for grp in payload.get("stats") or []:
        for split in grp.get("splits") or []:
            code = (split.get("split") or {}).get("code")
            pct = _k_pct(split.get("stat"))
            if code == "vr":
                k_vr = pct
            elif code == "vl":
                k_vl = pct
    return k_vr, k_vl


async def _fetch_window_k_pct(
    client: StatsApiClient,
    team_id: int,
    season: int,
    start: date,
    end: date,
) -> float | None:
    payload = await client.get_json(
        f"/api/v1/teams/{team_id}/stats",
        params={
            "stats": "byDateRange",
            "group": "hitting",
            "season": season,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        },
    )
    return _k_pct(_first_split_stat(payload))


# --- tonight's lineup --------------------------------------------------------


async def fetch_lineup_strength(
    client: StatsApiClient,
    game_pk: int,
    opponent_is_home: bool,
    season: int,
    pitcher_hand: Handedness | None = None,
) -> LineupStrength | None:
    """Tonight's projected lineup K% from the posted starting nine.

    Each batter's K% is PA-weighted. When ``pitcher_hand`` is supplied, uses
    the batter's handedness-split rate (vs RHP or vs LHP) rather than their
    overall season K% — a more precise signal since a power-hitting RHB may
    strike out 28% vs LHP but only 20% vs RHP. Falls back to overall season
    K% for any batter with fewer than 50 split PA. Returns ``None`` if the
    lineup hasn't been posted yet.
    """
    payload = await client.get_json(
        "/api/v1/schedule",
        params={"sportId": 1, "gamePk": game_pk, "hydrate": "lineups"},
    )
    lineup_ids = _lineup_player_ids(payload, game_pk, opponent_is_home)
    if not lineup_ids:
        return None

    MIN_SPLIT_PA = 50  # minimum PA in split to trust it over season average

    total_k = 0
    total_pa = 0
    for pid in lineup_ids:
        if pitcher_hand is not None:
            ks, pa = await _hitter_k_and_pa_vs_hand(client, pid, season, pitcher_hand)
            if pa < MIN_SPLIT_PA:
                ks, pa = await _hitter_k_and_pa(client, pid, season)
        else:
            ks, pa = await _hitter_k_and_pa(client, pid, season)
        total_k += ks
        total_pa += pa
    if total_pa <= 0:
        return None
    return LineupStrength(
        projected_lineup_k_pct=total_k / total_pa,
        high_k_hitters_resting=0,
    )


def _lineup_player_ids(
    payload: dict, game_pk: int, opponent_is_home: bool
) -> list[int]:
    key = "homePlayers" if opponent_is_home else "awayPlayers"
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            if game.get("gamePk") != game_pk:
                continue
            players = (game.get("lineups") or {}).get(key) or []
            return [p["id"] for p in players if p.get("id")]
    return []


async def _hitter_k_and_pa(
    client: StatsApiClient, player_id: int, season: int
) -> tuple[int, int]:
    payload = await client.get_json(
        f"/api/v1/people/{player_id}/stats",
        params={"stats": "season", "group": "hitting", "season": season},
    )
    stat = _first_split_stat(payload) or {}
    return int(stat.get("strikeOuts") or 0), int(stat.get("plateAppearances") or 0)


async def _hitter_k_and_pa_vs_hand(
    client: StatsApiClient,
    player_id: int,
    season: int,
    pitcher_hand: Handedness,
) -> tuple[int, int]:
    """Batter's K and PA against a specific pitcher handedness (vr = vs RHP, vl = vs LHP)."""
    sit_code = "vr" if pitcher_hand == Handedness.R else "vl"
    payload = await client.get_json(
        f"/api/v1/people/{player_id}/stats",
        params={
            "stats": "statSplits",
            "group": "hitting",
            "season": season,
            "sitCodes": sit_code,
        },
    )
    stat = _first_split_stat(payload) or {}
    return int(stat.get("strikeOuts") or 0), int(stat.get("plateAppearances") or 0)
