"""Objective 1 — compile the list of pitchers into the DuckDB store.

Mirror of ``compile_batters.py`` for the pitching side: pulls every pitcher with
an appearance in a season from the free MLB Stats API (season pitching splits,
paginated), enriches each with throwing handedness, and writes them to the
``pitchers`` table in ``data/baseball.duckdb`` keyed by (player_id, season).
Re-running replaces that season's rows (idempotent).

    python compile_pitchers.py            # current default season
    python compile_pitchers.py 2025 2024  # backfill specific seasons

The season rate line (K/9, BB/9, HR/9, GO/AO, ...) is enough to *list* pitchers
and seed a first-pass categorization; Statcast stuff (velo, spin, pitch mix,
whiff) for richer clustering (objective 2) gets layered on later.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

import duckdb

DB_PATH = "../data/baseball.duckdb"
API = "https://statsapi.mlb.com/api/v1"
PAGE = 100
DEFAULT_SEASON = 2026


def _get(url: str, attempts: int = 4) -> dict:
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed after {attempts}: {url}") from last


def _f(x) -> float | None:
    if x in (None, "", ".---", "-.--", "*.**", "-"):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ip(x) -> float | None:
    """MLB innings-pitched is '52.1' meaning 52 + 1/3. Convert to true innings."""
    if x in (None, ""):
        return None
    try:
        whole, _, frac = str(x).partition(".")
        return int(whole) + (int(frac) / 3 if frac else 0.0)
    except (TypeError, ValueError):
        return None


def fetch_pitchers(season: int) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{API}/stats?stats=season&group=pitching&season={season}"
            f"&gameType=R&playerPool=All&sportId=1&limit={PAGE}&offset={offset}"
        )
        block = _get(url)["stats"][0]
        splits = block.get("splits", [])
        if not splits:
            break
        for sp in splits:
            st = sp["stat"]
            ip = _ip(st.get("inningsPitched"))
            bf = st.get("battersFaced") or 0
            so = st.get("strikeOuts") or 0
            bb = st.get("baseOnBalls") or 0
            rows.append(
                {
                    "player_id": sp["player"]["id"],
                    "name": sp["player"]["fullName"],
                    "team_id": sp.get("team", {}).get("id"),
                    "team": sp.get("team", {}).get("name"),
                    "season": season,
                    "g": st.get("gamesPlayed"),
                    "gs": st.get("gamesStarted"),
                    "ip": round(ip, 2) if ip is not None else None,
                    "bf": bf,
                    "h": st.get("hits"),
                    "hr": st.get("homeRuns"),
                    "bb": bb,
                    "so": so,
                    "er": st.get("earnedRuns"),
                    "ground_outs": st.get("groundOuts"),
                    "air_outs": st.get("airOuts"),
                    "era": _f(st.get("era")),
                    "whip": _f(st.get("whip")),
                    "k_per_9": _f(st.get("strikeoutsPer9Inn")),
                    "bb_per_9": _f(st.get("walksPer9Inn")),
                    "hr_per_9": _f(st.get("homeRunsPer9")),
                    "go_ao": _f(st.get("groundOutsToAirouts")),
                    "k_pct": round(so / bf, 4) if bf else None,
                    "bb_pct": round(bb / bf, 4) if bf else None,
                    # role hint: share of appearances that were starts
                    "start_share": round((st.get("gamesStarted") or 0) / st.get("gamesPlayed"), 3)
                    if st.get("gamesPlayed") else None,
                }
            )
        offset += PAGE
        if offset >= block.get("totalSplits", 0):
            break
    return rows


def enrich_handedness(rows: list[dict]) -> None:
    ids = sorted({r["player_id"] for r in rows})
    throws: dict[int, str] = {}
    for i in range(0, len(ids), PAGE):
        chunk = ids[i : i + PAGE]
        url = (
            f"{API}/people?personIds={','.join(map(str, chunk))}"
            "&fields=people,id,pitchHand,code"
        )
        for p in _get(url).get("people", []):
            throws[p["id"]] = p.get("pitchHand", {}).get("code")
    for r in rows:
        r["throws"] = throws.get(r["player_id"])


COLUMNS = [
    "player_id", "name", "throws", "team_id", "team", "season",
    "g", "gs", "ip", "bf", "h", "hr", "bb", "so", "er",
    "ground_outs", "air_outs", "era", "whip", "k_per_9", "bb_per_9",
    "hr_per_9", "go_ao", "k_pct", "bb_pct", "start_share",
]


def store(rows: list[dict], season: int) -> int:
    con = duckdb.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pitchers (
            player_id BIGINT, name VARCHAR, throws VARCHAR,
            team_id INTEGER, team VARCHAR, season INTEGER,
            g INTEGER, gs INTEGER, ip DOUBLE, bf INTEGER, h INTEGER,
            hr INTEGER, bb INTEGER, so INTEGER, er INTEGER,
            ground_outs INTEGER, air_outs INTEGER, era DOUBLE, whip DOUBLE,
            k_per_9 DOUBLE, bb_per_9 DOUBLE, hr_per_9 DOUBLE, go_ao DOUBLE,
            k_pct DOUBLE, bb_pct DOUBLE, start_share DOUBLE,
            PRIMARY KEY (player_id, season)
        )
        """
    )
    con.execute("DELETE FROM pitchers WHERE season = ?", [season])
    con.executemany(
        f"INSERT INTO pitchers ({','.join(COLUMNS)}) VALUES ({','.join(['?'] * len(COLUMNS))})",
        [[r.get(c) for c in COLUMNS] for r in rows],
    )
    n = con.execute("SELECT count(*) FROM pitchers WHERE season = ?", [season]).fetchone()[0]
    con.close()
    return n


def main(argv: list[str]) -> int:
    seasons = [int(a) for a in argv] or [DEFAULT_SEASON]
    for season in seasons:
        print(f"[{season}] fetching pitchers…", flush=True)
        rows = fetch_pitchers(season)
        print(f"[{season}] {len(rows)} pitchers; fetching handedness…", flush=True)
        enrich_handedness(rows)
        n = store(rows, season)
        starters = sum(1 for r in rows if (r.get("ip") or 0) >= 30 and (r.get("start_share") or 0) >= 0.5)
        print(f"[{season}] stored {n} rows ({starters} starter-ish, IP>=30 & mostly starts) -> {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
