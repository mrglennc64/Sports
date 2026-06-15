"""Objectives 2 & 4 (v2) — categorize pitchers and batters on Statcast features.

Config-driven runner over :mod:`clusterlib`. For each role it joins the box-score
table with the Statcast table, clusters on plate-discipline + contact-quality
(+ velocity for pitchers) features, lets silhouette propose k, and (because these
skills form a continuum where silhouette favors a degenerate k=2) optionally
overrides to a k with useful archetype granularity. Writes per-player cluster id
back to the box-score table and an archetype summary table.

    python cluster_players.py batter  [k] [season]
    python cluster_players.py pitcher [k] [season]
    python cluster_players.py both
"""

from __future__ import annotations

import sys

import duckdb

import clusterlib as cl
import numpy as np

DB_PATH = "../data/baseball.duckdb"
DEFAULT_SEASON = 2026
MAX_K = 12
SEED = 7

# Each feature: (sql_expr, short, high_phrase, low_phrase)
CONFIG = {
    "batter": {
        "join": """
            SELECT b.player_id, b.name, b.bats AS hand, s.pa,
                   {feats}
            FROM batters b JOIN batter_statcast s
              ON b.player_id=s.player_id AND b.season=s.season
            WHERE b.season=? AND s.pa>=100
        """,
        "features": [
            ("s.k_percent",          "K%",      "high-K",        "contact"),
            ("s.bb_percent",         "BB%",     "patient",       "aggressive"),
            ("s.oz_swing_percent",   "Chase%",  "chaser",        "disciplined"),
            ("s.iz_contact_percent", "ZCon%",   "zone-contact",  "zone-whiff"),
            ("s.exit_velocity_avg",  "EV",      "hard-contact",  "soft-contact"),
            ("s.launch_angle_avg",   "LA",      "fly-ball/lift", "ground-ball"),
            ("s.barrel_batted_rate", "Brl%",    "barrels/power", "few-barrels"),
            ("CAST(b.sb AS DOUBLE)/b.pa*100", "SB%", "speed",    "station-to-station"),
        ],
        "cluster_col": "cluster_v2",
        "archetype_table": "batter_archetypes_v2",
        "default_k": 7,
    },
    "pitcher": {
        "join": """
            SELECT p.player_id, p.name, p.throws AS hand, s.pa,
                   {feats}
            FROM pitchers p JOIN pitcher_statcast s
              ON p.player_id=s.player_id AND p.season=s.season
            WHERE p.season=? AND s.pa>=50
        """,
        "features": [
            ("s.k_percent",           "K%",     "strikeout",        "pitch-to-contact"),
            ("s.bb_percent",          "BB%",    "wild",             "command"),
            ("s.whiff_percent",       "Whiff%", "swing-and-miss",   "low-whiff"),
            ("s.oz_swing_percent",    "Chase%", "chase-inducing",   "no-chase"),
            ("s.fastball_avg_speed",  "Velo",   "power-velo",       "finesse-velo"),
            ("s.groundballs_percent", "GB%",    "ground-ball",      "fly-ball"),
            ("s.barrel_batted_rate",  "Brl%",   "hittable",         "barrel-suppressing"),
        ],
        "cluster_col": "cluster_v2",
        "archetype_table": "pitcher_archetypes_v2",
        "default_k": 7,
    },
}


def run(role: str, forced_k: int | None, season: int) -> None:
    cfg = CONFIG[role]
    feats = cfg["features"]
    feat_sql = ", ".join(f"{e} AS f{i}" for i, (e, *_r) in enumerate(feats))
    con = duckdb.connect(DB_PATH)
    rows = con.execute(cfg["join"].format(feats=feat_sql), [season]).fetchall()
    con.close()

    # rows: player_id, name, hand, pa, f0..fn ; drop any with a NULL feature
    clean = [r for r in rows if all(v is not None for v in r[4:])]
    dropped = len(rows) - len(clean)
    ids = [r[0] for r in clean]
    names = [r[1] for r in clean]
    X = np.array([[float(v) for v in r[4:]] for r in clean], dtype=float)
    print(f"[{season}] {role}s: {len(clean)} with full features"
          + (f" ({dropped} dropped for missing data)" if dropped else "")
          + f"; features: {[f[1] for f in feats]}\n")

    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd

    scored = cl.scan_k(Z, MAX_K, SEED)
    for k, sil, *_ in scored:
        print(f"  k={k:>2}  silhouette={sil:.3f}")
    auto_k, auto_sil = max(scored, key=lambda t: t[1])[0:2]
    k = forced_k or cfg["default_k"]
    _, sil, lab, C = next(t for t in scored if t[0] == k)
    print(f"\n>>> silhouette picks k={auto_k} ({auto_sil:.3f}); "
          f"using k={k} ({sil:.3f}) for archetype granularity\n")

    phrases = [(f[2], f[3]) for f in feats]
    order = sorted(range(k), key=lambda j: -(lab == j).sum())
    archetypes = []
    for rank, j in enumerate(order):
        raw = C[j] * sd + mu
        size = int((lab == j).sum())
        label = cl.autoname(C[j], phrases)
        mem = np.where(lab == j)[0]
        d = ((Z[mem] - C[j]) ** 2).sum(1)
        ex = [names[mem[t]] for t in np.argsort(d)[:3]]
        archetypes.append((j, rank, size, label, raw, ex))
        feat_str = "  ".join(f"{feats[i][1]} {raw[i]:.1f}" for i in range(len(feats)))
        print(f"[{rank+1}] {label:<34} n={size:<3} {feat_str}")
        print(f"     e.g. {', '.join(ex)}")

    # persist
    con = duckdb.connect(DB_PATH)
    table = "batters" if role == "batter" else "pitchers"
    col = cfg["cluster_col"]
    con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} INTEGER")
    con.execute(f"UPDATE {table} SET {col}=NULL WHERE season=?", [season])
    con.executemany(
        f"UPDATE {table} SET {col}=? WHERE player_id=? AND season=?",
        [[int(lab[i]), ids[i], season] for i in range(len(ids))],
    )
    fcols = ", ".join(f"{f[1].strip('%').lower().replace('/','_')} DOUBLE" for f in feats)
    fnames = [f[1].strip('%').lower().replace('/', '_') for f in feats]
    at = cfg["archetype_table"]
    con.execute(f"DROP TABLE IF EXISTS {at}")
    con.execute(f"CREATE TABLE {at} (season INTEGER, cluster INTEGER, rank INTEGER, "
                f"label VARCHAR, size INTEGER, {fcols})")
    con.executemany(
        f"INSERT INTO {at} VALUES (?,?,?,?,?,{','.join(['?']*len(fnames))})",
        [[season, int(j), rank, label, size, *[float(raw[i]) for i in range(len(feats))]]
         for (j, rank, size, label, raw, _ex) in archetypes],
    )
    con.close()
    print(f"\nwrote {table}.{col} + {at} for {season}\n")


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    role = argv[0]
    forced_k = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else None
    season = int(argv[2]) if len(argv) > 2 else DEFAULT_SEASON
    roles = ["batter", "pitcher"] if role == "both" else [role]
    for r in roles:
        run(r, forced_k, season)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
