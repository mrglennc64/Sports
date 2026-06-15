"""Compile a rolling, multi-season plate-appearance (PA) database into DuckDB.

This is objective 5 of the type-matchup program: the historical game database the
pitcher-type x batter-type -> outcome matrix (objective 6) is built on. The grain
is ONE ROW PER PLATE APPEARANCE (not per pitch) — each PA carries the batter id,
pitcher id, the handedness matchup, and the final outcome (``events``), which is
exactly what's needed to cross-reference cluster labels and tally outcomes by type.

Source: Baseball Savant's public ``statcast_search`` CSV (pitch-level, no key) —
same host the backend's data/savant.py uses. We download pitch rows in small date
windows (Savant caps a single response at ~25k rows) and keep only the PA-ending
rows (``events`` non-empty), discarding intermediate pitches so the table stays
~185k rows/season instead of ~700k.

Stored to ``pa_events`` keyed (game_pk, at_bat_number). Idempotent per season
(re-running a season replaces it). Regular + postseason kept; ``game_type`` stored
so analysis can filter (R = regular season).

    python compile_games.py [season ...]      # default: one recent full season

Backfill the rolling ~10-season window with:
    python compile_games.py 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026
"""
from __future__ import annotations

import csv
import io
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import duckdb

DB_PATH = "../data/baseball.duckdb"
SAVANT = "https://baseballsavant.mlb.com/statcast_search/csv"
DEFAULT_SEASONS = [2024]  # one complete season for a first verification run

# Date window per request. Savant truncates a response at ~25k pitch rows; a full
# game day is ~4.4k pitches, so a 4-day window (~18k) stays safely under the cap.
CHUNK_DAYS = 4
CAP_WARN = 24000  # if a window returns this many pitch rows, it may be truncated
SLEEP_S = 1.0     # be polite to Savant between requests
RETRIES = 3

# Season window: mid-March (Opening Day / late spring) through mid-November
# (covers regular season + postseason). Future-dated chunks just return 0 rows.
SEASON_START = (3, 15)
SEASON_END = (11, 15)

# Savant CSV column -> stored column (kept same name unless noted).
INT_COLS = ["game_pk", "at_bat_number", "inning", "balls", "strikes",
            "pitch_number", "batter", "pitcher"]
FLOAT_COLS = ["launch_speed", "launch_angle"]
TEXT_COLS = ["game_date", "game_type", "stand", "p_throws", "events",
             "description", "bb_type", "pitch_type", "home_team", "away_team",
             "player_name"]


def _window_url(start: date, end: date) -> str:
    return (
        f"{SAVANT}?all=true&type=details&player_type=pitcher&min_pitches=0"
        f"&game_date_gt={start:%Y-%m-%d}&game_date_lt={end:%Y-%m-%d}"
    )


def _fetch(url: str) -> list[dict]:
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            txt = urllib.request.urlopen(req, timeout=180).read().decode("utf-8-sig")
            return list(csv.DictReader(io.StringIO(txt)))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(SLEEP_S * attempt * 2)
    raise RuntimeError(f"fetch failed after {RETRIES} tries: {last}")


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pa_events (
            season       INTEGER,
            game_pk      INTEGER,
            game_date    DATE,
            game_type    VARCHAR,
            at_bat_number INTEGER,
            inning       INTEGER,
            batter       INTEGER,
            pitcher      INTEGER,
            stand        VARCHAR,
            p_throws     VARCHAR,
            events       VARCHAR,
            description  VARCHAR,
            bb_type      VARCHAR,
            pitch_type   VARCHAR,
            balls        INTEGER,
            strikes      INTEGER,
            pitches_in_pa INTEGER,
            launch_speed DOUBLE,
            launch_angle DOUBLE,
            home_team    VARCHAR,
            away_team    VARCHAR,
            player_name  VARCHAR,
            PRIMARY KEY (game_pk, at_bat_number)
        )
        """
    )


def _row(season: int, r: dict) -> tuple | None:
    if not r.get("events"):
        return None  # keep only PA-ending rows
    gpk = _to_int(r.get("game_pk"))
    ab = _to_int(r.get("at_bat_number"))
    if gpk is None or ab is None:
        return None
    return (
        season, gpk, r.get("game_date") or None, r.get("game_type") or None, ab,
        _to_int(r.get("inning")), _to_int(r.get("batter")), _to_int(r.get("pitcher")),
        r.get("stand") or None, r.get("p_throws") or None,
        r.get("events") or None, r.get("description") or None,
        r.get("bb_type") or None, r.get("pitch_type") or None,
        _to_int(r.get("balls")), _to_int(r.get("strikes")),
        _to_int(r.get("pitch_number")),
        _to_float(r.get("launch_speed")), _to_float(r.get("launch_angle")),
        r.get("home_team") or None, r.get("away_team") or None,
        r.get("player_name") or None,
    )


def compile_season(con: duckdb.DuckDBPyConnection, season: int) -> int:
    start = date(season, *SEASON_START)
    end = date(season, *SEASON_END)
    con.execute("DELETE FROM pa_events WHERE season = ?", [season])

    total = 0
    cur = start
    while cur <= end:
        wend = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        pitches = _fetch(_window_url(cur, wend))
        if len(pitches) >= CAP_WARN:
            print(f"  WARN {cur}..{wend}: {len(pitches)} pitch rows — may hit the "
                  f"25k cap; consider a smaller CHUNK_DAYS", flush=True)
        # de-dup within the window by (game_pk, at_bat_number); the final pitch of
        # each PA carries events, so distinct PA keys are guaranteed unique.
        rows = {}
        for r in pitches:
            row = _row(season, r)
            if row is not None:
                rows[(row[1], row[4])] = row
        if rows:
            con.executemany(
                "INSERT OR REPLACE INTO pa_events VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                list(rows.values()),
            )
            total += len(rows)
        print(f"  {cur:%Y-%m-%d}..{wend:%Y-%m-%d}: {len(pitches):>5} pitches -> "
              f"{len(rows):>4} PAs  (season total {total})", flush=True)
        time.sleep(SLEEP_S)
        cur = wend + timedelta(days=1)
    return total


def main(argv: list[str]) -> None:
    seasons = [int(a) for a in argv] if argv else DEFAULT_SEASONS
    con = duckdb.connect(DB_PATH)
    _ensure_table(con)
    for s in seasons:
        print(f"=== season {s} ===", flush=True)
        n = compile_season(con, s)
        print(f"season {s}: {n} plate appearances stored", flush=True)
    # quick summary
    rows = con.execute(
        "SELECT season, count(*) FROM pa_events GROUP BY season ORDER BY season"
    ).fetchall()
    print("--- pa_events by season ---")
    for s, n in rows:
        print(f"  {s}: {n}")
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
