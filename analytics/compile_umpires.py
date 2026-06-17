"""Compute REAL home-plate-umpire K tendencies from MLB data (replaces placeholders).

umpscorecards.com has a clean API but only call-ACCURACY metrics — no strikeout
rate — so it can't populate the model's umpire factor (which needs k_rate = Ks per
PA in that umpire's games). This computes the right metric directly: the MLB Stats
API gives the HP umpire per game (boxscore officials), and pa_events_reg already
has every PA + strikeout, so we join them.

Two steps, both idempotent/resumable:
  1. Fill `game_umpire` (game_pk -> HP umpire) for every regular-season game_pk in
     pa_events_reg not already cached (one boxscore fetch each; resumes on re-run).
  2. Per umpire: n_games, n_pa, n_k -> k_rate. Write ../data/umpires.json in the
     backend's expected format for umpires with >= MIN_GAMES.

    python compile_umpires.py [min_games]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

import duckdb

DB = "../data/baseball.duckdb"
OUT = "../data/umpires.json"
MIN_GAMES = 15
SLEEP_S = 0.08
RETRIES = 3
LEAGUE_K = 0.22


def _get(url: str) -> dict:
    last = None
    for a in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            last = e
            time.sleep(SLEEP_S * a * 4)
    raise RuntimeError(f"fetch failed: {last}")


def _hp_umpire(game_pk: int) -> str | None:
    box = _get(f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore")
    for o in box.get("officials") or []:
        if o.get("officialType") == "Home Plate":
            return (o.get("official") or {}).get("fullName")
    return None


def main(argv: list[str]) -> None:
    min_games = int(argv[0]) if argv else MIN_GAMES
    con = duckdb.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS game_umpire "
                "(game_pk INTEGER PRIMARY KEY, umpire VARCHAR)")

    todo = [r[0] for r in con.execute("""
        SELECT DISTINCT game_pk FROM pa_events_reg
        WHERE game_pk NOT IN (SELECT game_pk FROM game_umpire)
        ORDER BY game_pk
    """).fetchall()]
    print(f"games needing umpire lookup: {len(todo)}", flush=True)

    done = 0
    for gpk in todo:
        try:
            ump = _hp_umpire(gpk)
        except Exception as e:
            print(f"  skip {gpk}: {e}", flush=True)
            ump = None
        con.execute("INSERT OR REPLACE INTO game_umpire VALUES (?,?)", [gpk, ump])
        done += 1
        if done % 250 == 0:
            print(f"  {done}/{len(todo)} fetched", flush=True)
        time.sleep(SLEEP_S)
    print(f"game_umpire now covers "
          f"{con.execute('SELECT count(*) FROM game_umpire').fetchone()[0]} games", flush=True)

    # per-umpire K/PA over regular-season PAs
    rows = con.execute("""
        SELECT gu.umpire,
               count(DISTINCT e.game_pk) AS n_games,
               count(*) AS n_pa,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') AS n_k
        FROM pa_events_reg e
        JOIN game_umpire gu ON gu.game_pk = e.game_pk
        WHERE gu.umpire IS NOT NULL
        GROUP BY 1
    """).fetchall()
    con.close()

    table = {
        "_comment": ("Home-plate umpire K tendencies computed from MLB Stats API "
                     "HP-umpire assignments x pa_events_reg (2024-2026 regular "
                     f"season). k_rate = strikeouts per PA in that umpire's games "
                     f"(league avg ~{LEAGUE_K}). Min {min_games} games. Generated "
                     "by analytics/compile_umpires.py."),
        "_league_average_k_rate": LEAGUE_K,
    }
    kept = []
    for ump, n_games, n_pa, n_k in rows:
        if n_games < min_games:
            continue
        kr = round(n_k / n_pa, 4)
        table[ump] = {"k_rate": kr, "n_games": n_games, "n_pa": n_pa}
        kept.append((ump, kr, n_games))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2, sort_keys=True)

    kept.sort(key=lambda t: t[1])
    print(f"\nwrote {OUT}: {len(kept)} umpires (>= {min_games} games)")
    print("lowest-K umpires:")
    for u, kr, g in kept[:5]:
        print(f"  {u:22} {kr:.3f}  ({g} g)")
    print("highest-K umpires:")
    for u, kr, g in kept[-5:][::-1]:
        print(f"  {u:22} {kr:.3f}  ({g} g)")


if __name__ == "__main__":
    main(sys.argv[1:])
