"""Pull pitcher pitch-mix (arsenal usage %) from Baseball Savant into DuckDB.

Completes the pitcher taxonomy (offspeed-dominant / power-fastball types) using the
free Savant pitch-arsenals leaderboard — usage % per pitch type. We roll the
individual pitches into three buckets:
  fastball% = FF + SI + FC          (four-seam, sinker, cutter)
  offspeed% = CH + FS               (changeup, splitter)
  breaking% = SL + CU + ST + SV + KN (slider, curve, sweeper, slurve, knuckle)
Stored to `pitcher_arsenal` keyed (player_id, season). Idempotent per season.

    python compile_arsenal.py [season ...]
"""
from __future__ import annotations

import csv
import io
import sys
import time
import urllib.request

import duckdb

DB_PATH = "../data/baseball.duckdb"
URL = ("https://baseballsavant.mlb.com/leaderboard/pitch-arsenals"
       "?year={year}&min=100&type=n_&hand=&csv=true")
DEFAULT_SEASON = 2026

FASTBALL = ["n_ff", "n_si", "n_fc"]
OFFSPEED = ["n_ch", "n_fs"]
BREAKING = ["n_sl", "n_cu", "n_st", "n_sv", "n_kn"]


def _get(url: str, attempts: int = 4) -> str:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed after {attempts}: {url}") from last


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def fetch(season: int) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(_get(URL.format(year=season)))):
        pid = r.get("pitcher")
        if not pid:
            continue
        fb = sum(_f(r.get(c)) for c in FASTBALL)
        off = sum(_f(r.get(c)) for c in OFFSPEED)
        brk = sum(_f(r.get(c)) for c in BREAKING)
        rows.append({
            "player_id": int(pid), "season": season,
            "fastball_pct": round(fb, 1), "offspeed_pct": round(off, 1),
            "breaking_pct": round(brk, 1),
        })
    return rows


def main(argv) -> int:
    seasons = [int(a) for a in argv] or [DEFAULT_SEASON]
    con = duckdb.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS pitcher_arsenal (
        player_id BIGINT, season INTEGER, fastball_pct DOUBLE,
        offspeed_pct DOUBLE, breaking_pct DOUBLE, PRIMARY KEY (player_id, season))""")
    for season in seasons:
        rows = fetch(season)
        con.execute("DELETE FROM pitcher_arsenal WHERE season=?", [season])
        con.executemany(
            "INSERT INTO pitcher_arsenal VALUES (?,?,?,?,?)",
            [[r["player_id"], r["season"], r["fastball_pct"],
              r["offspeed_pct"], r["breaking_pct"]] for r in rows],
        )
        print(f"[{season}] pitcher_arsenal: stored {len(rows)} pitchers", flush=True)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
