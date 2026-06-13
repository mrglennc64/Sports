"""Assemble real historical games into :class:`GameOutcome` records.

This is the bridge from the live MLB Stats API data layer to the backtest +
weight tuner in :mod:`app.model.backtest`. For each probable start on a past
date we reconstruct a point-in-time :class:`~app.model.inputs.ProjectionInputs`
(using ONLY information knowable before first pitch), fetch the pitcher's ACTUAL
strikeouts for that date from the pitching gameLog, and attach an OPTIONAL
user-supplied betting line. The result is a ``list[GameOutcome]`` that
``run_backtest`` / ``tune_weights`` consume directly — no synthetic data.

Point-in-time correctness (look-ahead bias / data leakage)
----------------------------------------------------------
A clean backtest must only use information knowable *before first pitch on
``on_date``*. Unlike :func:`app.data.assemble.build_projection_inputs` (which is
built for TODAY's games, where season-to-date == as-of), this module
reconstructs every input as-of ``on_date``:

  * ``recent_start_ks`` — built from gameLog starts strictly BEFORE ``on_date``.
  * ``k_per_9_last_30`` — aggregated from gameLog appearances in the 30 days
    BEFORE ``on_date`` only.
  * ``workload`` (expected innings / pitch count) — derived from gameLog
    IP / games-started accumulated BEFORE ``on_date`` only.
  * opponent recent windows (last 14 / 30) — byDateRange ending the day BEFORE
    ``on_date``.
  * opponent vs-RHP / vs-LHP — the as-of overall team K% LEVEL (byDateRange to
    the day before ``on_date``) scaled by the season-long handedness RATIO. See
    the note below.
  * ``lineup`` K% — each posted hitter's K% over byDateRange ending the day
    BEFORE ``on_date``; falls back to the as-of team rate if no lineup posted.
  * ``umpire`` — the assigned home-plate umpire is knowable at game time
    (looked up only when an umpire table is supplied).

Residual, documented approximation: the free MLB Stats API only exposes
handedness (vs RHP/LHP) splits as FULL-SEASON ``statSplits`` — ``byDateRange``
ignores ``sitCodes``. So we take the as-of overall K% *level* and apply the
season's relative R/L *tilt* (a structurally stable ratio). Only that tilt
borrows full-season data; the magnitude is as-of. Baseball Savant factors
(swing/CSW, pitch mix) are season-to-date and are intentionally NOT used here.

Betting lines
-------------
Closing / historical strikeout prop lines are NOT available from the free MLB
Stats API, and the project's odds provider serves only CURRENT lines. We do NOT
fabricate lines. They are user-supplied via a mapping or CSV
(:func:`load_lines_csv`). When a line is absent, ``GameOutcome.line`` is
``None`` and only accuracy metrics apply.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from typing import Mapping

from app.data.client import StatsApiClient
from app.data.mlb_stats import ProbableStart, fetch_probable_starts, parse_innings
from app.data.umpires import UmpireTable, fetch_umpire_profile
from app.model.backtest import (
    BacktestResult,
    ComponentWeights,
    GameOutcome,
    ModelConfig,
    run_backtest,
    tune_weights,
)
from app.model.inputs import (
    BullpenContext,
    ExpectedWorkload,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
)

# A line mapping is keyed by either (date, pitcher_name) or (date, pitcher_id).
LineKey = tuple[str, str] | tuple[str, int]
LineMapping = Mapping[LineKey, float]

LEAGUE_AVG_K_RATE = 0.22
PITCHES_PER_INNING = 16.0
DEFAULT_HOOK_PITCH_COUNT = 100.0
MIN_IP_PER_START = 3.0
MAX_IP_PER_START = 7.0
NEUTRAL_IP_PER_START = (MIN_IP_PER_START + MAX_IP_PER_START) / 2
RECENT_STARTS = 5
K9_WINDOW_DAYS = 30
# Bullpen / opener leash (the sub-3-IP signal the [3,7] clamp above discards).
NORMAL_START_IP = 5.5            # a full, healthy start
OPENER_IP_THRESHOLD = 3.0       # avg IP/start below this => opener / bulk role
MIN_APPEARANCES_FOR_LEASH = 3   # need this many prior starts before trusting it


def _season_of(on_date: str) -> int:
    return date.fromisoformat(on_date).year


def _norm_name(name: str) -> str:
    return name.strip().lower()


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _lookup_line(
    lines: LineMapping | None, on_date: str, start: ProbableStart
) -> float | None:
    """Find a user-supplied line for this start, by id first then by name."""
    if not lines:
        return None
    if (on_date, start.pitcher_id) in lines:
        return lines[(on_date, start.pitcher_id)]
    target = _norm_name(start.pitcher_name)
    for key, value in lines.items():
        kdate, who = key
        if kdate != on_date:
            continue
        if isinstance(who, str) and _norm_name(who) == target:
            return value
    return None


# --------------------------------------------------------------------------- #
# Pitcher gameLog (one fetch feeds actual Ks, recent form, k/9, workload)
# --------------------------------------------------------------------------- #
async def _fetch_gamelog_splits(
    client: StatsApiClient, pitcher_id: int, season: int
) -> list[dict]:
    """Raw gameLog splits (oldest-first) for one pitcher's season."""
    payload = await client.get_json(
        f"/api/v1/people/{pitcher_id}",
        params={
            "hydrate": f"stats(group=[pitching],type=[gameLog],season={season})"
        },
    )
    people = payload.get("people") or []
    if not people:
        return []
    stats = people[0].get("stats") or []
    if not stats:
        return []
    return stats[0].get("splits") or []


def _actual_ks_on(splits: list[dict], on_date: str) -> int | None:
    """Actual strikeouts the pitcher recorded on ``on_date`` (None if no final)."""
    for split in splits:
        if split.get("date") == on_date:
            ks = (split.get("stat") or {}).get("strikeOuts")
            return int(ks) if ks is not None else None
    return None


def _splits_before(splits: list[dict], on_date: str) -> list[dict]:
    """gameLog splits strictly before ``on_date`` (preserves oldest-first order)."""
    cutoff = date.fromisoformat(on_date)
    return [
        s
        for s in splits
        if s.get("date") and date.fromisoformat(s["date"]) < cutoff
    ]


def _recent_start_ks_before(
    splits: list[dict], on_date: str, recent_starts: int = RECENT_STARTS
) -> list[int]:
    """Ks from the pitcher's starts strictly BEFORE ``on_date`` (newest-first)."""
    prior_starts = [
        s for s in _splits_before(splits, on_date)
        if (s.get("stat") or {}).get("gamesStarted")
    ]
    prior_starts.reverse()  # oldest-first -> newest-first
    return [
        int(s["stat"]["strikeOuts"])
        for s in prior_starts[:recent_starts]
        if s.get("stat", {}).get("strikeOuts") is not None
    ]


def _asof_workload_and_k9(
    splits: list[dict], on_date: str
) -> tuple[ExpectedWorkload, float, BullpenContext]:
    """As-of workload + K/9 + bullpen leash, from appearances BEFORE ``on_date``.

    ``expected_innings`` = IP/start over all prior starts (clamped 3-7);
    ``k_per_9`` is over the prior ``K9_WINDOW_DAYS`` days only. The
    ``BullpenContext`` is derived from the RAW (unclamped) IP/start so it can
    express the opener / short-leash volume cap that the [3,7] clamp on
    ``expected_innings`` would otherwise erase. All point-in-time.
    """
    prior = _splits_before(splits, on_date)
    cutoff = date.fromisoformat(on_date)
    k9_start = cutoff - timedelta(days=K9_WINDOW_DAYS)

    total_ip = 0.0
    games_started = 0
    win_k = 0
    win_ip = 0.0
    for s in prior:
        stat = s.get("stat") or {}
        ip = parse_innings(stat.get("inningsPitched", "0"))
        total_ip += ip
        games_started += int(stat.get("gamesStarted") or 0)
        if date.fromisoformat(s["date"]) >= k9_start:
            win_k += int(stat.get("strikeOuts") or 0)
            win_ip += ip

    if games_started > 0 and total_ip > 0:
        raw_ip_per_start = total_ip / games_started
        ip_per_start = min(MAX_IP_PER_START, max(MIN_IP_PER_START, raw_ip_per_start))
    else:
        raw_ip_per_start = NEUTRAL_IP_PER_START
        ip_per_start = NEUTRAL_IP_PER_START

    k_per_9 = (win_k / win_ip * 9.0) if win_ip > 0 else 0.0

    workload = ExpectedWorkload(
        expected_innings=ip_per_start,
        expected_pitch_count=ip_per_start * PITCHES_PER_INNING,
        manager_hook_pitch_count=DEFAULT_HOOK_PITCH_COUNT,
    )
    bullpen = _bullpen_from_ip(raw_ip_per_start, games_started)
    return workload, k_per_9, bullpen


def _bullpen_from_ip(raw_ip_per_start: float, games_started: int) -> BullpenContext:
    """Opener / short-leash volume signal from raw IP-per-start. Point-in-time.

    Below ``MIN_APPEARANCES_FOR_LEASH`` prior starts the sample is too thin to
    trust, so we stay neutral (leash 1.0). Otherwise the leash is the prior
    volume relative to a normal start, capped at 1.0 (this factor only ever
    *trims* for low-volume roles; it never inflates a workhorse, since
    ``expected_innings`` already carries upside volume).
    """
    if games_started < MIN_APPEARANCES_FOR_LEASH:
        return BullpenContext(is_opener=False, leash_factor=1.0)
    leash = min(1.0, max(0.25, raw_ip_per_start / NORMAL_START_IP))
    return BullpenContext(
        is_opener=raw_ip_per_start < OPENER_IP_THRESHOLD,
        leash_factor=leash,
    )


# --------------------------------------------------------------------------- #
# As-of opponent profile and lineup
# --------------------------------------------------------------------------- #
def _k_pct(stat: dict | None) -> float | None:
    if not stat:
        return None
    pa = stat.get("plateAppearances") or 0
    if not pa:
        return None
    return (stat.get("strikeOuts") or 0) / pa


def _first_split_stat(payload: dict) -> dict | None:
    stats = payload.get("stats") or []
    if not stats:
        return None
    splits = stats[0].get("splits") or []
    if not splits:
        return None
    return splits[0].get("stat")


async def _window_team_k_pct(
    client: StatsApiClient, team_id: int, season: int, start: date, end: date
) -> float | None:
    """Team K% over [start, end] (inclusive) from byDateRange hitting."""
    if end < start:
        return None
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


async def _season_vr_vl_counts(
    client: StatsApiClient, team_id: int, season: int
) -> tuple[float | None, float | None, float | None]:
    """Season (rate_vr, rate_vl, rate_overall) from full-season statSplits.

    Used ONLY for the structural R/L tilt ratio; the level is applied as-of.
    The overall is the vr+vl aggregate (every PA faces an R or L pitcher).
    """
    payload = await client.get_json(
        f"/api/v1/teams/{team_id}/stats",
        params={
            "stats": "statSplits",
            "group": "hitting",
            "season": season,
            "sitCodes": "vr,vl",
        },
    )
    k_vr = pa_vr = k_vl = pa_vl = None
    for grp in payload.get("stats") or []:
        for split in grp.get("splits") or []:
            code = (split.get("split") or {}).get("code")
            stat = split.get("stat") or {}
            if code == "vr":
                k_vr, pa_vr = stat.get("strikeOuts"), stat.get("plateAppearances")
            elif code == "vl":
                k_vl, pa_vl = stat.get("strikeOuts"), stat.get("plateAppearances")

    rate_vr = (k_vr / pa_vr) if k_vr is not None and pa_vr else None
    rate_vl = (k_vl / pa_vl) if k_vl is not None and pa_vl else None
    overall = None
    if None not in (k_vr, pa_vr, k_vl, pa_vl) and (pa_vr + pa_vl):
        overall = (k_vr + k_vl) / (pa_vr + pa_vl)
    return rate_vr, rate_vl, overall


async def _asof_opponent_profile(
    client: StatsApiClient,
    team_id: int,
    season: int,
    on_date: str,
    lineup_k_pct: float | None,
) -> OpponentKProfile:
    """Opponent K profile reconstructed as-of ``on_date`` (see module docstring)."""
    end = date.fromisoformat(on_date)
    end_excl = end - timedelta(days=1)  # the opponent's game today hasn't happened
    season_start = date(season, 1, 1)  # byDateRange clamps to the real season start

    overall_asof = await _window_team_k_pct(client, team_id, season, season_start, end_excl)
    k14 = await _window_team_k_pct(client, team_id, season, end - timedelta(days=14), end_excl)
    k30 = await _window_team_k_pct(client, team_id, season, end - timedelta(days=30), end_excl)
    rate_vr_s, rate_vl_s, overall_s = await _season_vr_vl_counts(client, team_id, season)

    base = overall_asof or k30 or k14 or rate_vr_s or rate_vl_s or LEAGUE_AVG_K_RATE

    def _tilt(rate_season: float | None) -> float:
        # Apply the season's R/L tilt to the as-of level; neutral if unavailable.
        if rate_season is not None and overall_s:
            return _clamp01(base * (rate_season / overall_s))
        return base

    k14f = k14 or base
    return OpponentKProfile(
        k_pct_vs_rhp=_tilt(rate_vr_s),
        k_pct_vs_lhp=_tilt(rate_vl_s),
        k_pct_last_14=k14f,
        k_pct_last_30=k30 or base,
        k_pct_starting_lineup=lineup_k_pct if lineup_k_pct is not None else k14f,
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


async def _asof_hitter_k_pa(
    client: StatsApiClient, player_id: int, season: int, start: date, end: date
) -> tuple[int, int]:
    if end < start:
        return 0, 0
    payload = await client.get_json(
        f"/api/v1/people/{player_id}/stats",
        params={
            "stats": "byDateRange",
            "group": "hitting",
            "season": season,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        },
    )
    stat = _first_split_stat(payload) or {}
    return int(stat.get("strikeOuts") or 0), int(stat.get("plateAppearances") or 0)


async def _asof_lineup(
    client: StatsApiClient,
    game_pk: int,
    opponent_is_home: bool,
    season: int,
    on_date: str,
) -> LineupStrength | None:
    """As-of lineup K% from the posted nine; None if no lineup posted."""
    payload = await client.get_json(
        "/api/v1/schedule",
        params={"sportId": 1, "gamePk": game_pk, "hydrate": "lineups"},
    )
    ids = _lineup_player_ids(payload, game_pk, opponent_is_home)
    if not ids:
        return None

    end = date.fromisoformat(on_date)
    end_excl = end - timedelta(days=1)
    season_start = date(season, 1, 1)

    total_k = total_pa = 0
    for pid in ids:
        ks, pa = await _asof_hitter_k_pa(client, pid, season, season_start, end_excl)
        total_k += ks
        total_pa += pa
    if total_pa <= 0:
        return None
    return LineupStrength(
        projected_lineup_k_pct=_clamp01(total_k / total_pa),
        high_k_hitters_resting=0,
    )


# --------------------------------------------------------------------------- #
# Full point-in-time inputs for one start
# --------------------------------------------------------------------------- #
async def _build_asof_inputs(
    client: StatsApiClient,
    start: ProbableStart,
    on_date: str,
    season: int,
    splits: list[dict],
    umpire_table: UmpireTable | None,
) -> ProjectionInputs:
    """Reconstruct a leak-free ``ProjectionInputs`` for one historical start."""
    workload, k_per_9, bullpen = _asof_workload_and_k9(splits, on_date)
    recent_ks = _recent_start_ks_before(splits, on_date)
    form = PitcherRecentForm(
        throws=start.throws,
        recent_start_ks=recent_ks,
        k_per_9_last_30=k_per_9,
        swinging_strike_pct=None,
        csw_pct=None,
    )

    # The opponent is home exactly when the pitcher's team is NOT.
    lineup = await _asof_lineup(
        client, start.game_pk, not start.is_home, season, on_date
    )
    lineup_k_pct = lineup.projected_lineup_k_pct if lineup else None
    opponent = await _asof_opponent_profile(
        client, start.opponent_team_id, season, on_date, lineup_k_pct
    )
    if lineup is None:
        lineup = LineupStrength(
            projected_lineup_k_pct=opponent.k_pct_starting_lineup,
            high_k_hitters_resting=0,
        )

    umpire = None
    if umpire_table:
        umpire = await fetch_umpire_profile(client, start.game_pk, umpire_table)

    return ProjectionInputs(
        pitcher_name=start.pitcher_name,
        opponent=opponent,
        pitcher_form=form,
        workload=workload,
        lineup=lineup,
        umpire=umpire,
        pitch_mix=None,  # season-to-date Savant data would leak; omitted here
        bullpen=bullpen,
        # weather/catcher reconstructed by separate as-of fetchers; omitted
        # here until their historical sources are wired (kept neutral).
    )


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
async def load_history_for_date(
    client: StatsApiClient,
    on_date: str,
    season: int | None = None,
    lines: LineMapping | None = None,
    umpire_table: UmpireTable | None = None,
) -> list[GameOutcome]:
    """Build point-in-time :class:`GameOutcome`s for every final start on ``on_date``.

    Starts with no final result (actual Ks ``None`` — game not played / not
    final / pitcher scratched) are skipped.
    """
    season = season or _season_of(on_date)
    starts = await fetch_probable_starts(client, on_date)

    outcomes: list[GameOutcome] = []
    for start in starts:
        splits = await _fetch_gamelog_splits(client, start.pitcher_id, season)
        actual_ks = _actual_ks_on(splits, on_date)
        if actual_ks is None:
            continue  # no final result for this start; skip

        inputs = await _build_asof_inputs(
            client, start, on_date, season, splits, umpire_table
        )
        line = _lookup_line(lines, on_date, start)
        outcomes.append(GameOutcome(inputs=inputs, actual_ks=actual_ks, line=line))
    return outcomes


def _date_range(start_date: str, end_date: str) -> list[str]:
    """Inclusive list of ISO dates from ``start_date`` to ``end_date``."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


async def load_history_range(
    client: StatsApiClient,
    start_date: str,
    end_date: str,
    lines: LineMapping | None = None,
    umpire_table: UmpireTable | None = None,
) -> list[GameOutcome]:
    """Concatenate :func:`load_history_for_date` over an inclusive date range."""
    outcomes: list[GameOutcome] = []
    for on_date in _date_range(start_date, end_date):
        outcomes.extend(
            await load_history_for_date(
                client, on_date, lines=lines, umpire_table=umpire_table
            )
        )
    return outcomes


# --------------------------------------------------------------------------- #
# Betting lines from a user CSV
# --------------------------------------------------------------------------- #
def load_lines_csv(path: str) -> dict[LineKey, float]:
    """Load user-supplied strikeout prop lines from a simple CSV.

    Expected columns (header row required, order-independent):
        date,pitcher,line[,over_odds,under_odds]

    ``date`` is ISO ``YYYY-MM-DD``. ``pitcher`` may be a pitcher name OR a
    numeric MLB pitcher id; numeric values are keyed by ``(date, int_id)`` and
    names by ``(date, name)``. ``over_odds`` / ``under_odds`` are accepted for
    forward-compatibility but ignored today (the backtester assumes -110). Rows
    with a missing or non-numeric ``line`` are skipped.

    Because historical/closing odds are not available from any wired-up
    provider, this file is the ONLY honest source of lines — nothing is faked.
    """
    out: dict[LineKey, float] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            on_date = (row.get("date") or "").strip()
            pitcher = (row.get("pitcher") or "").strip()
            raw_line = (row.get("line") or "").strip()
            if not on_date or not pitcher or not raw_line:
                continue
            try:
                line = float(raw_line)
            except ValueError:
                continue
            key: LineKey = (on_date, int(pitcher)) if pitcher.isdigit() else (on_date, pitcher)
            out[key] = line
    return out


# --------------------------------------------------------------------------- #
# Convenience: load history + run the backtest (optionally tune)
# --------------------------------------------------------------------------- #
async def backtest_range(
    client: StatsApiClient,
    start: str,
    end: str,
    lines: LineMapping | None = None,
    base_cfg: ModelConfig | None = None,
    *,
    tune: bool = False,
    objective: str = "mae",
) -> tuple[BacktestResult, ComponentWeights | None]:
    """Load real point-in-time history over ``[start, end]`` then run the backtest.

    Returns ``(result, tuned_weights)``. When ``tune`` is False the second item
    is ``None``; otherwise weights are tuned on the loaded dataset for
    ``objective`` ("mae" or "roi") and the returned ``result`` is recomputed
    with them. Betting metrics appear only if some game carried a line.
    """
    dataset = await load_history_range(client, start, end, lines=lines)
    cfg = base_cfg or ModelConfig()

    tuned: ComponentWeights | None = None
    if tune:
        tuned, _ = tune_weights(dataset, cfg, objective=objective)  # type: ignore[arg-type]
        cfg = cfg.model_copy(update={"weights": tuned})

    return run_backtest(dataset, cfg), tuned
