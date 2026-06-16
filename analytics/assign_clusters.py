"""Objective 6 prep — assign prior-season players to the 2026 archetype centroids.

The v2 clusters (cluster_players.py) are fit on 2026 only. To pool multiple
seasons into ONE pitcher-type x batter-type outcome matrix with a single, stable
label set (user decision 2026-06-16), every prior-season player is assigned to
their NEAREST 2026 centroid in the same standardized feature space — so a "P5
strikeout/power-velo" pitcher means the same thing in 2024 as in 2026.

Recipe (identical features + scaling to cluster_players.py):
  1. Load 2026 qualified players + their stored cluster_v2 labels.
  2. Standardize features with the 2026 mean/std; centroid[j] = mean of the
     standardized features over 2026 members of cluster j (this reproduces the
     k-means centroids, since a k-means centroid is the mean of its members).
  3. For each target season, standardize with the SAME 2026 mean/std and assign
     argmin Euclidean distance to a centroid. Write cluster_v2 for that season.

Requires the target seasons' feature tables first (compile_batters/pitchers +
compile_statcast for those seasons).

    python assign_clusters.py [season ...]      # default: 2024 2025
"""
from __future__ import annotations

import sys
from collections import Counter

import duckdb
import numpy as np

import cluster_players as cp

REF_SEASON = 2026
DEFAULT_TARGETS = [2024, 2025]


def _load(con: duckdb.DuckDBPyConnection, role: str, season: int):
    """Return (ids, X) for qualified players — same SQL/features as clustering."""
    cfg = cp.CONFIG[role]
    feats = cfg["features"]
    feat_sql = ", ".join(f"{e} AS f{i}" for i, (e, *_r) in enumerate(feats))
    rows = con.execute(cfg["join"].format(feats=feat_sql), [season]).fetchall()
    clean = [r for r in rows if all(v is not None for v in r[4:])]
    ids = [r[0] for r in clean]
    X = np.array([[float(v) for v in r[4:]] for r in clean], dtype=float)
    return ids, X


def run(role: str, targets: list[int]) -> None:
    cfg = cp.CONFIG[role]
    col = cfg["cluster_col"]
    table = "batters" if role == "batter" else "pitchers"
    con = duckdb.connect(cp.DB_PATH)

    # 1. reference 2026 features + stored labels
    ids26, X26 = _load(con, role, REF_SEASON)
    lab26 = {
        r[0]: r[1]
        for r in con.execute(
            f"SELECT player_id, {col} FROM {table} WHERE season=? AND {col} IS NOT NULL",
            [REF_SEASON],
        ).fetchall()
    }
    keep = [i for i, pid in enumerate(ids26) if pid in lab26]
    if not keep:
        print(f"[{role}] no 2026 cluster_v2 labels found — run cluster_players first")
        con.close()
        return
    X26 = X26[keep]
    y26 = np.array([lab26[ids26[i]] for i in keep])

    # 2. 2026 scaler + centroids (standardized space)
    mu, sd = X26.mean(0), X26.std(0)
    sd[sd == 0] = 1.0
    Z26 = (X26 - mu) / sd
    clusters = sorted(set(int(v) for v in y26))
    C = np.array([Z26[y26 == j].mean(0) for j in clusters])

    # 3. assign each target season
    for season in targets:
        ids, X = _load(con, role, season)
        if not ids:
            print(f"[{season}] {role}: no qualified players — backfill features first")
            continue
        Z = (X - mu) / sd
        dist = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(2)  # n x k
        nearest = dist.argmin(1)
        assign = [clusters[k] for k in nearest]
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} INTEGER")
        con.execute(f"UPDATE {table} SET {col}=NULL WHERE season=?", [season])
        con.executemany(
            f"UPDATE {table} SET {col}=? WHERE player_id=? AND season=?",
            [[int(assign[i]), ids[i], season] for i in range(len(ids))],
        )
        d = Counter(assign)
        print(f"[{season}] {role}: assigned {len(ids)} -> "
              + ", ".join(f"c{j}:{d[j]}" for j in clusters))
    con.close()


def main(argv: list[str]) -> int:
    targets = [int(a) for a in argv] if argv else DEFAULT_TARGETS
    for role in ("batter", "pitcher"):
        run(role, targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
