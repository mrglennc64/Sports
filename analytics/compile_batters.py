"""Objective 3 — compile the list of batters into the DuckDB store.

Pulls every hitter with a plate appearance in a season from the free MLB Stats
API (season hitting splits, paginated), enriches each with batting handedness,
and writes them to the ``batters`` table in ``data/baseball.duckdb`` keyed by
(player_id, season). Re-running replaces that season's rows (idempotent), so the
same script extends the database to more seasons later:

    python compile_batters.py            # current default season
    python compile_batters.py 2025 2024  # backfill specific seasons

The season stat line here (K%, BB%, ISO, OPS, ...) is enough to *list* batters
and seed a first-pass categorization; the richer plate-discipline / Statcast
features for clustering (objective 4) get layered on later.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

import duckdb

DB_PATH = "../data/baseball.duckdb"
API = "https://statsapi.mlb.com/api/v1"
PAGE = 100  # MLB API splits page size
DEFAULT_SEASON = 2026


def _get(url: str, attempts: int = 4) -> dict:
    """GET JSON with a small backoff retry."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — transient network/HTTP
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed after {attempts}: {url}") from last


def _f(x) -> float | None:
    """Parse MLB's stringy stat numbers ('.300', '1.000', '.---') to float."""
    if x in (None, "", ".---", "-.--", "*.**"):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_hitters(season: int) -> list[dict]:
    """All hitters (playerPool=All) with a season hitting line, paginated."""
    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{API}/stats?stats=season&group=hitting&season={season}"
            f"&gameType=R&playerPool=All&sportId=1&limit={PAGE}&offset={offset}"
        )
        block = _get(url)["stats"][0]
        splits = block.get("splits", [])
        if not splits:
            break
        for sp in splits:
            st = sp["stat"]
            pa = st.get("plateAppearances") or 0
            so = st.get("strikeOuts") or 0
            bb = st.get("baseOnBalls") or 0
            slg = _f(st.get("slg"))
            avg = _f(st.get("avg"))
            rows.append(
                {
                    "player_id": sp["player"]["id"],
                    "name": sp["player"]["fullName"],
                    "team_id": sp.get("team", {}).get("id"),
                    "team": sp.get("team", {}).get("name"),
                    "position": sp.get("position", {}).get("abbreviation"),
                    "season": season,
                    "g": st.get("gamesPlayed"),
                    "pa": pa,
                    "ab": st.get("atBats"),
                    "h": st.get("hits"),
                    "doubles": st.get("doubles"),
                    "triples": st.get("triples"),
                    "hr": st.get("homeRuns"),
                    "bb": bb,
                    "so": so,
                    "hbp": st.get("hitByPitch"),
                    "sb": st.get("stolenBases"),
                    "tb": st.get("totalBases"),
                    "avg": avg,
                    "obp": _f(st.get("obp")),
                    "slg": slg,
                    "ops": _f(st.get("ops")),
                    "k_pct": round(so / pa, 4) if pa else None,
                    "bb_pct": round(bb / pa, 4) if pa else None,
                    "iso": round(slg - avg, 4) if (slg is not None and avg is not None) else None,
                }
            )
        offset += PAGE
        if offset >= block.get("totalSplits", 0):
            break
    return rows


def enrich_handedness(rows: list[dict]) -> None:
    """Fill each row's ``bats`` (L/R/S) via the people endpoint, batched."""
    ids = sorted({r["player_id"] for r in rows})
    bats: dict[int, str] = {}
    for i in range(0, len(ids), PAGE):
        chunk = ids[i : i + PAGE]
        url = (
            f"{API}/people?personIds={','.join(map(str, chunk))}"
            "&fields=people,id,batSide,code"
        )
        for p in _get(url).get("people", []):
            bats[p["id"]] = p.get("batSide", {}).get("code")
    for r in rows:
        r["bats"] = bats.get(r["player_id"])


COLUMNS = [
    "player_id", "name", "bats", "team_id", "team", "position", "season",
    "g", "pa", "ab", "h", "doubles", "triples", "hr", "bb", "so", "hbp",
    "sb", "tb", "avg", "obp", "slg", "ops", "k_pct", "bb_pct", "iso",
]


def store(rows: list[dict], season: int) -> int:
    con = duckdb.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS batters (
            player_id BIGINT, name VARCHAR, bats VARCHAR,
            team_id INTEGER, team VARCHAR, position VARCHAR, season INTEGER,
            g INTEGER, pa INTEGER, ab INTEGER, h INTEGER, doubles INTEGER,
            triples INTEGER, hr INTEGER, bb INTEGER, so INTEGER, hbp INTEGER,
            sb INTEGER, tb INTEGER, avg DOUBLE, obp DOUBLE, slg DOUBLE,
            ops DOUBLE, k_pct DOUBLE, bb_pct DOUBLE, iso DOUBLE,
            PRIMARY KEY (player_id, season)
        )
        """
    )
    con.execute("DELETE FROM batters WHERE season = ?", [season])
    con.executemany(
        f"INSERT INTO batters ({','.join(COLUMNS)}) VALUES ({','.join(['?'] * len(COLUMNS))})",
        [[r.get(c) for c in COLUMNS] for r in rows],
    )
    n = con.execute("SELECT count(*) FROM batters WHERE season = ?", [season]).fetchone()[0]
    con.close()
    return n


def main(argv: list[str]) -> int:
    seasons = [int(a) for a in argv] or [DEFAULT_SEASON]
    for season in seasons:
        print(f"[{season}] fetching hitters…", flush=True)
        rows = fetch_hitters(season)
        print(f"[{season}] {len(rows)} hitters; fetching handedness…", flush=True)
        enrich_handedness(rows)
        n = store(rows, season)
        qualified = sum(1 for r in rows if (r["pa"] or 0) >= 100)
        print(f"[{season}] stored {n} rows ({qualified} with PA>=100) -> {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
