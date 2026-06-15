"""Pull Baseball Savant (Statcast) per-player leaderboard features into DuckDB.

The box-score rates from the MLB Stats API don't separate batter/pitcher
archetypes cleanly (they're power-dominated → clustering collapsed). Statcast adds
the discriminating signal: plate discipline (chase / whiff / contact) and
contact quality (exit velo, launch angle, barrel%, hard-hit%), plus pitch
velocity for pitchers.

Source: the public Savant **custom leaderboard** CSV (read-only, no key) — same
CSV quirks the backend's data/savant.py documents (UTF-8 BOM; first header is the
quoted ``"last_name, first_name"``). Stored to ``batter_statcast`` /
``pitcher_statcast`` keyed (player_id, season). Idempotent per season.

    python compile_statcast.py [season ...]
"""

from __future__ import annotations

import csv
import io
import sys
import time
import urllib.request

import duckdb

DB_PATH = "../data/baseball.duckdb"
SAVANT = "https://baseballsavant.mlb.com/leaderboard/custom"
DEFAULT_SEASON = 2026
# Savant's `min` = minimum PA (batter) / batters-faced (pitcher). Batters use 100
# to match our qualified set; the pitcher endpoint returns nothing above ~100, so
# 50 (≈ all starters + established relievers) is the usable threshold.
MIN_BATTER = 100
MIN_PITCHER = 50

# metric column name in the Savant CSV  ->  stored column (same name kept)
BATTER_METRICS = [
    "pa", "k_percent", "bb_percent", "whiff_percent", "swing_percent",
    "oz_swing_percent", "oz_contact_percent", "iz_contact_percent",
    "exit_velocity_avg", "launch_angle_avg", "sweet_spot_percent",
    "barrel_batted_rate", "hard_hit_percent",
]
PITCHER_METRICS = [
    "pa", "k_percent", "bb_percent", "whiff_percent", "swing_percent",
    "oz_swing_percent", "fastball_avg_speed", "exit_velocity_avg",
    "launch_angle_avg", "barrel_batted_rate", "hard_hit_percent",
    "groundballs_percent",
]


def _get(url: str, attempts: int = 4) -> str:
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed after {attempts}: {url}") from last


def _f(x):
    if x is None or x.strip() == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def fetch(kind: str, season: int, metrics: list[str]) -> list[dict]:
    sel = ",".join(metrics)
    min_pa = MIN_BATTER if kind == "batter" else MIN_PITCHER
    url = (
        f"{SAVANT}?year={season}&type={kind}&filter=&min={min_pa}"
        f"&selections={sel}&chart=false&x=k_percent&y=k_percent&r=no"
        f"&chartType=beeswarm&sort=pa&sortDir=desc&csv=true"
    )
    text = _get(url)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        rows.append(
            {
                "player_id": int(r["player_id"]),
                "name": r.get("last_name, first_name", "").strip('"'),
                "season": season,
                **{m: _f(r.get(m)) for m in metrics},
            }
        )
    return rows


def store(table: str, metrics: list[str], rows: list[dict], season: int) -> int:
    cols = ["player_id", "name", "season", *metrics]
    coldefs = ", ".join(
        f"{c} {'BIGINT' if c == 'player_id' else 'VARCHAR' if c == 'name' else 'INTEGER' if c == 'season' else 'DOUBLE'}"
        for c in cols
    )
    con = duckdb.connect(DB_PATH)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {table} ({coldefs}, PRIMARY KEY (player_id, season))"
    )
    con.execute(f"DELETE FROM {table} WHERE season = ?", [season])
    con.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
        [[r.get(c) for c in cols] for r in rows],
    )
    n = con.execute(f"SELECT count(*) FROM {table} WHERE season = ?", [season]).fetchone()[0]
    con.close()
    return n


def main(argv):
    seasons = [int(a) for a in argv] or [DEFAULT_SEASON]
    for season in seasons:
        for kind, table, metrics in (
            ("batter", "batter_statcast", BATTER_METRICS),
            ("pitcher", "pitcher_statcast", PITCHER_METRICS),
        ):
            print(f"[{season}] fetching {kind} statcast…", flush=True)
            rows = fetch(kind, season, metrics)
            if not rows:
                print(f"[{season}] {table}: no rows returned — skipped")
                continue
            n = store(table, metrics, rows, season)
            print(f"[{season}] {table}: stored {n} rows -> {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
