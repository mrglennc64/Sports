"""Export the pitcher-type x batter-type matchup matrix to a viz-ready CSV.

Pools every regular-season PA whose batter AND pitcher both carry a cluster
label (2026 from clustering; 2024-2025 from nearest-2026-centroid assignment),
exactly the same population build_matrix.py uses for `matchup_outcomes`. Each PA
joins to its OWN season's player labels; the 2026 archetype names are canonical
(every season's players sit on the same 2026 centroids).

For each (pitcher_group, batter_group) cell it computes the standard slash line
plus K/BB/batted-ball rates, and writes one row per cell to
../data/matchup_matrix.csv with the exact header/column order:

    pitcher_group,batter_group,PA,AVG,OBP,SLG,wOBA,K_rate,BB_rate,
    GB_rate,FB_rate,HardHit_rate

This is the GROUP-LEVEL matrix that deliberately replaces noisy individual
batter-vs-pitcher H2H lines (individual matchups of <4 PA are excluded by
design — they carry no signal). Group cells carry thousands of PAs, so the
PA >= 100 guard below never actually bites here; it is kept as a safety rail.

No pandas in the analytics venv (Python 3.14, duckdb only) — we read via
.execute(...).fetchall() and write the CSV with the stdlib csv module.

    python export_matchup_csv.py
"""
from __future__ import annotations

import csv
import re

import duckdb

DB = "../data/baseball.duckdb"
OUT_CSV = "../data/matchup_matrix.csv"
REF_SEASON = 2026          # canonical archetype label season
MIN_PA = 100               # cell inclusion guard (safety rail; cells are large)

HEADER = ["pitcher_group", "batter_group", "PA", "AVG", "OBP", "SLG", "wOBA",
          "K_rate", "BB_rate", "GB_rate", "FB_rate", "HardHit_rate"]


def slug(label: str) -> str:
    """Sanitize an archetype label into a snake_case group id.

    lowercase; spaces / slashes / hyphens -> underscore; strip any remaining
    non-alphanumeric/underscore chars; collapse repeated underscores; trim.
    e.g. "strikeout / power-velo" -> "strikeout_power_velo".
    """
    s = label.lower()
    s = re.sub(r"[\s/\-]+", "_", s)        # whitespace, slash, hyphen -> "_"
    s = re.sub(r"[^a-z0-9_]+", "", s)      # drop anything else
    s = re.sub(r"_+", "_", s)              # collapse repeats
    return s.strip("_")


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    # One row per (pitcher cluster, batter cluster) cell. All counting is done
    # in SQL with FILTER(...); every rate denominator is wrapped in NULLIF(.,0)
    # so empty denominators yield NULL rather than a divide-by-zero error.
    #
    # wOBA uses 2023 FanGraphs linear weights:
    #   uBB 0.69, HBP 0.72, 1B 0.89, 2B 1.27, 3B 1.62, HR 2.10
    # The numerator counts UNINTENTIONAL walks only (intentional walks are
    # excluded from wOBA), and the denominator is AB + uBB + SF + HBP.
    rows = con.execute(f"""
        WITH pa AS (
          SELECT e.events, e.bb_type, e.launch_speed,
                 pit.cluster_v2 AS p_cl, bat.cluster_v2 AS b_cl
          FROM pa_events_reg e
          JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
          JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
          WHERE pit.cluster_v2 IS NOT NULL AND bat.cluster_v2 IS NOT NULL
        ),
        cell AS (
          SELECT
            p_cl, b_cl,
            count(*)                                                   AS pa,
            count(*) FILTER (WHERE events LIKE 'strikeout%')           AS k,
            count(*) FILTER (WHERE events='walk')                      AS ubb,
            count(*) FILTER (WHERE events='intent_walk')               AS ibb,
            count(*) FILTER (WHERE events='hit_by_pitch')              AS hbp,
            count(*) FILTER (WHERE events='home_run')                  AS hr,
            count(*) FILTER (WHERE events='single')                    AS b1,
            count(*) FILTER (WHERE events='double')                    AS b2,
            count(*) FILTER (WHERE events='triple')                    AS b3,
            count(*) FILTER (WHERE events IN ('sac_fly','sac_fly_double_play')) AS sf,
            count(*) FILTER (WHERE events='sac_bunt')                  AS sh,
            -- batted-ball denominators / numerators
            count(*) FILTER (WHERE bb_type IN
                ('ground_ball','fly_ball','line_drive','popup'))       AS bip,
            count(*) FILTER (WHERE bb_type='ground_ball')              AS gb,
            count(*) FILTER (WHERE bb_type='fly_ball')                 AS fb,
            count(*) FILTER (WHERE launch_speed IS NOT NULL)           AS bbe,
            count(*) FILTER (WHERE launch_speed >= 95)                 AS hardhit
          FROM pa GROUP BY p_cl, b_cl
        ),
        derived AS (
          SELECT
            p_cl, b_cl, pa,
            (pa - ubb - ibb - hbp - sf - sh)        AS ab,
            (b1 + b2 + b3 + hr)                      AS h,
            k, ubb, ibb, hbp, hr, b1, b2, b3, sf, sh, bip, gb, fb, bbe, hardhit
          FROM cell
        )
        SELECT
          pl.label AS pitcher_label,
          bl.label AS batter_label,
          d.pa,
          round(h::DOUBLE / nullif(ab, 0), 3)                       AS avg,
          -- OBP = (H + BB + HBP) / (AB + BB + HBP + SF) = (..)/(PA - SH).
          round((h + ubb + ibb + hbp)::DOUBLE
                / nullif(pa - sh, 0), 3)                            AS obp,
          round((b1 + 2*b2 + 3*b3 + 4*hr)::DOUBLE
                / nullif(ab, 0), 3)                                 AS slg,
          -- wOBA (2023 FanGraphs weights; unintentional walks only).
          round((0.69*ubb + 0.72*hbp + 0.89*b1 + 1.27*b2
                 + 1.62*b3 + 2.10*hr)
                / nullif(ab + ubb + sf + hbp, 0), 3)                AS woba,
          round(d.k::DOUBLE / nullif(pa, 0), 3)                     AS k_rate,
          round(ubb::DOUBLE / nullif(pa, 0), 3)                     AS bb_rate,
          round(d.gb::DOUBLE / nullif(bip, 0), 3)                   AS gb_rate,
          round(fb::DOUBLE  / nullif(bip, 0), 3)                    AS fb_rate,
          round(hardhit::DOUBLE / nullif(bbe, 0), 3)                AS hardhit_rate
        FROM derived d
        JOIN pitcher_archetypes_v2 pl
          ON pl.season={REF_SEASON} AND pl.cluster=d.p_cl
        JOIN batter_archetypes_v2  bl
          ON bl.season={REF_SEASON} AND bl.cluster=d.b_cl
        WHERE d.pa >= {MIN_PA}
        ORDER BY pl.label, bl.label
    """).fetchall()

    con.close()

    # Build CSV rows, slugging the labels into snake_case group ids.
    out_rows = []
    for r in rows:
        (p_label, b_label, pa, avg, obp, slg, woba,
         k_rate, bb_rate, gb_rate, fb_rate, hardhit_rate) = r
        out_rows.append([
            slug(p_label), slug(b_label), int(pa),
            avg, obp, slg, woba,
            k_rate, bb_rate, gb_rate, fb_rate, hardhit_rate,
        ])

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(out_rows)

    # ---- report ---------------------------------------------------------
    total_pa = sum(row[2] for row in out_rows)
    print(f"wrote {len(out_rows)} cells to {OUT_CSV}")
    print(f"total PA across cells: {total_pa}")

    # wOBA is column index 6 (HEADER). Sort, skipping any NULL wOBA cells.
    rated = [row for row in out_rows if row[6] is not None]
    by_woba = sorted(rated, key=lambda row: row[6])

    print("\nlowest wOBA cells:")
    for row in by_woba[:3]:
        print(f"  {row[6]:.3f}  {row[0]} vs {row[1]}  (PA={row[2]})")
    print("highest wOBA cells:")
    for row in reversed(by_woba[-3:]):
        print(f"  {row[6]:.3f}  {row[0]} vs {row[1]}  (PA={row[2]})")


if __name__ == "__main__":
    main()
