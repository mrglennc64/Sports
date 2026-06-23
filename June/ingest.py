"""June pipeline — raw per-game play-by-play transfer (Savant + MLB Stats API).

Pure data transfer, strict source fidelity. One DuckDB (mlb_2025.duckdb) with a
SCHEMA PER 2025 regular-season game:
  game_<pk>.savant_pitches  -- raw Baseball Savant statcast_search (all 119 cols,
                               every pitch, original names/order; all-VARCHAR so
                               no value is altered by type inference)
  game_<pk>.mlb_allplays    -- raw MLB Stats API feed/live play-by-play (allPlays,
                               nested, original field names). Falls back to a raw
                               JSON blob if the nested structure won't tabularize.
No filtering, transformation, aggregation, calculation, prediction, or enrichment.
Idempotent + resumable: games already ingested (schema exists) are skipped.

    python ingest.py [--limit N] [--db mlb_2025.duckdb]
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request

import duckdb

SCHED = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&season=2025&gameType=R"
SAVANT = ("https://baseballsavant.mlb.com/statcast_search/csv"
          "?all=true&type=details&game_pk={pk}")
FEED = "https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def game_pks() -> list[int]:
    d = json.loads(_get(SCHED))
    return [g["gamePk"] for day in d["dates"] for g in day["games"]]


def ingest_game(con, pk: int, tmp: str) -> str:
    schema = f"game_{pk}"
    if con.execute("SELECT count(*) FROM information_schema.schemata "
                   "WHERE schema_name=?", [schema]).fetchone()[0]:
        return "skip"
    con.execute(f'CREATE SCHEMA "{schema}"')

    # 1) Savant raw pitch table (all_varchar = exact fidelity, no type coercion)
    try:
        txt = _get(SAVANT.format(pk=pk)).decode("utf-8-sig")
        if txt.count("\n") > 1:
            f = os.path.join(tmp, f"sv_{pk}.csv")
            open(f, "w", encoding="utf-8", newline="").write(txt)
            con.execute(f'CREATE TABLE "{schema}".savant_pitches AS '
                        f"SELECT * FROM read_csv(?, all_varchar=true, header=true, "
                        f"sample_size=-1)", [f])
        else:
            con.execute(f'CREATE TABLE "{schema}".savant_pitches (no_data BOOLEAN)')
    except Exception as e:  # noqa: BLE001
        con.execute(f'CREATE TABLE "{schema}".savant_pitches (error VARCHAR)')
        con.execute(f'INSERT INTO "{schema}".savant_pitches VALUES (?)', [str(e)[:500]])

    # 2) MLB feed/live raw play-by-play (allPlays)
    try:
        feed = json.loads(_get(FEED.format(pk=pk)))
        plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
        if plays:
            f = os.path.join(tmp, f"pbp_{pk}.json")
            open(f, "w", encoding="utf-8").write(json.dumps(plays))
            try:
                con.execute(f'CREATE TABLE "{schema}".mlb_allplays AS '
                            f"SELECT * FROM read_json_auto(?, maximum_object_size=1000000000)", [f])
            except Exception:  # nested structure won't tabularize -> keep raw JSON
                con.execute(f'CREATE TABLE "{schema}".mlb_allplays (allplays_json JSON)')
                con.execute(f'INSERT INTO "{schema}".mlb_allplays VALUES (?)',
                            [json.dumps(plays)])
        else:
            con.execute(f'CREATE TABLE "{schema}".mlb_allplays (no_data BOOLEAN)')
    except Exception as e:  # noqa: BLE001
        con.execute(f'CREATE TABLE "{schema}".mlb_allplays (error VARCHAR)')
        con.execute(f'INSERT INTO "{schema}".mlb_allplays VALUES (?)', [str(e)[:500]])
    return "done"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all games")
    ap.add_argument("--db", default="mlb_2025.duckdb")
    ap.add_argument("--sleep", type=float, default=0.25)
    a = ap.parse_args()

    pks = game_pks()
    if a.limit:
        pks = pks[: a.limit]
    print(f"2025 regular-season game records: {len(pks)}", flush=True)

    con = duckdb.connect(a.db)
    tmp = tempfile.mkdtemp()
    done = skip = err = 0
    for i, pk in enumerate(pks, 1):
        try:
            r = ingest_game(con, pk, tmp)
            done += (r == "done"); skip += (r == "skip")
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  ERR game {pk}: {str(e)[:200]}", flush=True)
        if i % 50 == 0 or i == len(pks):
            print(f"  {i}/{len(pks)}  ingested={done} skipped={skip} err={err}", flush=True)
        time.sleep(a.sleep)
    print(f"DONE: {done} ingested, {skip} skipped, {err} errors -> {a.db}")
    con.close()


if __name__ == "__main__":
    main()
