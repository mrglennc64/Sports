"""Objective 4 — analyze & categorize batters; let the DATA pick the # of clusters.

Loads qualified batters from ``data/baseball.duckdb``, clusters them on a small
set of interpretable, outcome-relevant rate features, and chooses k by maximizing
the mean silhouette over k = 2..MAX_K (so the number of archetypes falls out of
the data, not a hardcode). Each cluster is auto-named from its centroid (which
features deviate, and which way), written back to the DB as:

  * ``batters.cluster_v1``     — per-batter cluster id for the season
  * ``batter_archetypes_v1``   — one row per (season, cluster): label, size, means

This is the v1 categorization on MLB-Stats-API features (contact / patience /
power / speed). Statcast plate-discipline + contact-quality features (chase%,
exit velo, launch angle) will refine it in a later pass.

    python cluster_batters.py [season] [min_pa]
"""

from __future__ import annotations

import sys

import duckdb
import numpy as np

DB_PATH = "../data/baseball.duckdb"
DEFAULT_SEASON = 2026
DEFAULT_MIN_PA = 100
MAX_K = 10
SEED = 7

# (db expression, short feature name, human axis, +z means…)
FEATURES = [
    ("k_pct",                         "K%",   "contact",  "more swing-and-miss"),
    ("bb_pct",                        "BB%",  "patience", "more patient"),
    ("iso",                           "ISO",  "power",    "more extra-base power"),
    ("CAST(hr AS DOUBLE)/pa",         "HR%",  "hr",       "more home-run power"),
    ("CAST(sb AS DOUBLE)/pa",         "SB%",  "speed",    "more basestealing"),
    ("CAST(doubles+triples AS DOUBLE)/pa", "XBH%", "gap", "more gap/doubles power"),
]


def load(season: int, min_pa: int):
    con = duckdb.connect(DB_PATH)
    cols = ", ".join(f"{expr} AS f{i}" for i, (expr, *_2) in enumerate(FEATURES))
    rows = con.execute(
        f"SELECT player_id, name, bats, pa, {cols} FROM batters "
        "WHERE season=? AND pa>=? ORDER BY pa DESC",
        [season, min_pa],
    ).fetchall()
    con.close()
    ids = [r[0] for r in rows]
    names = [r[1] for r in rows]
    pa = [r[3] for r in rows]
    X = np.array([[float(v) for v in r[4:]] for r in rows], dtype=float)
    return ids, names, pa, X


def kmeans(X, k, seed, iters=200, restarts=12):
    """k-means++ init, best of several restarts (lowest inertia). Pure numpy."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        # k-means++ seeding
        c = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d2 = np.min(((X[:, None, :] - np.array(c)[None, :, :]) ** 2).sum(2), axis=1)
            probs = d2 / d2.sum()
            c.append(X[rng.choice(len(X), p=probs)])
        C = np.array(c)
        for _ in range(iters):
            lab = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(2), axis=1)
            newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j]
                             for j in range(k)])
            if np.allclose(newC, C):
                C = newC
                break
            C = newC
        inertia = sum(((X[lab == j] - C[j]) ** 2).sum() for j in range(k))
        if best is None or inertia < best[2]:
            best = (lab, C, inertia)
    return best[0], best[1]


def silhouette(X, lab):
    """Mean silhouette coefficient. O(n^2) — fine for a few hundred points."""
    D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(2))
    n = len(X)
    labs = np.unique(lab)
    if len(labs) < 2:
        return -1.0
    s = np.zeros(n)
    for i in range(n):
        same = lab == lab[i]
        same[i] = False
        a = D[i, same].mean() if same.any() else 0.0
        b = min(D[i, lab == j].mean() for j in labs if j != lab[i])
        s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean())


def autoname(zc):
    """Name an archetype from its standardized centroid (zc over FEATURES)."""
    # strongest deviations first
    order = sorted(range(len(zc)), key=lambda i: -abs(zc[i]))
    parts = []
    for i in order[:2]:
        if abs(zc[i]) < 0.45:
            continue
        axis = FEATURES[i][2]
        hi = zc[i] > 0
        phrase = {
            ("contact", True): "high-K", ("contact", False): "contact",
            ("patience", True): "patient", ("patience", False): "aggressive",
            ("power", True): "power", ("power", False): "low-power",
            ("hr", True): "HR power", ("hr", False): "few HR",
            ("speed", True): "speed", ("speed", False): "station-to-station",
            ("gap", True): "gap power", ("gap", False): "few XBH",
        }[(axis, hi)]
        parts.append(phrase)
    return " / ".join(parts) if parts else "balanced / average"


def main(argv):
    season = int(argv[0]) if len(argv) > 0 else DEFAULT_SEASON
    min_pa = int(argv[1]) if len(argv) > 1 else DEFAULT_MIN_PA
    # Optional 3rd arg forces k. Silhouette on this (continuum) data maxes at the
    # coarsest k=2 while staying nearly flat for k=3..10, so we override to a k
    # that gives useful archetype granularity for the downstream matchup matrix.
    forced_k = int(argv[2]) if len(argv) > 2 else None
    ids, names, pa, X = load(season, min_pa)
    print(f"[{season}] clustering {len(X)} batters (PA>={min_pa}) on "
          f"{len(FEATURES)} features: {[f[1] for f in FEATURES]}\n")

    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd

    # let the data choose k
    scored = []
    for k in range(2, MAX_K + 1):
        lab, C = kmeans(Z, k, SEED)
        sil = silhouette(Z, lab)
        scored.append((k, sil, lab, C))
        print(f"  k={k:>2}  silhouette={sil:.3f}")
    auto_k, auto_sil = max(scored, key=lambda t: t[1])[0:2]
    print(f"\n>>> silhouette picks k = {auto_k}  (silhouette {auto_sil:.3f})")
    if forced_k:
        best_k, _best_sil, lab, C = next(t for t in scored if t[0] == forced_k)
        print(f">>> overriding to k = {forced_k} for archetype granularity "
              f"(silhouette {_best_sil:.3f}, ~flat vs auto)\n")
    else:
        best_k, best_sil, lab, C = max(scored, key=lambda t: t[1])
        print()

    # characterize clusters, ordered by size
    sizes = [(j, int((lab == j).sum())) for j in range(best_k)]
    sizes.sort(key=lambda t: -t[1])
    archetypes = []
    for rank, (j, size) in enumerate(sizes):
        zc = C[j]                      # centroid in z-space
        raw = zc * sd + mu             # centroid back in raw units
        label = autoname(zc)
        # 3 exemplars: closest to centroid
        members = np.where(lab == j)[0]
        d = ((Z[members] - C[j]) ** 2).sum(1)
        exemplars = [names[members[t]] for t in np.argsort(d)[:3]]
        archetypes.append((j, rank, size, label, raw, exemplars))
        feat_str = "  ".join(f"{FEATURES[i][1]} {raw[i]:.3f}" for i in range(len(FEATURES)))
        print(f"[{rank+1}] {label:<28} n={size:<3}  {feat_str}")
        print(f"     e.g. {', '.join(exemplars)}")

    # write back
    con = duckdb.connect(DB_PATH)
    con.execute("ALTER TABLE batters ADD COLUMN IF NOT EXISTS cluster_v1 INTEGER")
    con.execute("UPDATE batters SET cluster_v1=NULL WHERE season=?", [season])
    con.executemany("UPDATE batters SET cluster_v1=? WHERE player_id=? AND season=?",
                    [[int(lab[i]), ids[i], season] for i in range(len(ids))])
    con.execute("""CREATE TABLE IF NOT EXISTS batter_archetypes_v1 (
        season INTEGER, cluster INTEGER, rank INTEGER, label VARCHAR, size INTEGER,
        k_pct DOUBLE, bb_pct DOUBLE, iso DOUBLE, hr_rate DOUBLE, sb_rate DOUBLE, xbh_rate DOUBLE
    )""")
    con.execute("DELETE FROM batter_archetypes_v1 WHERE season=?", [season])
    con.executemany(
        "INSERT INTO batter_archetypes_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [[season, int(j), rank, label, size, *[float(raw[i]) for i in range(len(FEATURES))]]
         for (j, rank, size, label, raw, _ex) in archetypes],
    )
    con.close()
    print(f"\nwrote batters.cluster_v1 + batter_archetypes_v1 for {season}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
