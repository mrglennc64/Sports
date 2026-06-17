"""Objective 6 — pitcher-type x batter-type -> outcome matrix.

Pools every regular-season PA whose batter AND pitcher both carry a cluster label
(2026 from clustering; 2024-2025 from assign_clusters' nearest-2026-centroid), and
tallies ALL plate-appearance outcomes by (pitcher_cluster, batter_cluster). Each PA
joins to its OWN season's player labels; the 2026 archetype names are canonical
(every season's players sit on the same 2026 centroids).

Stored as RAW COUNTS (`matchup_outcomes`) — the iterable canonical form, so any
rate can be re-derived or pooled further — plus a convenience `matchup_rates` view.

    python build_matrix.py
"""
from __future__ import annotations

import duckdb

DB = "../data/baseball.duckdb"
REF_SEASON = 2026

OUT_EVENTS = ("field_out", "force_out", "grounded_into_double_play",
              "double_play", "triple_play", "fielders_choice",
              "fielders_choice_out", "strikeout_double_play")


def main() -> None:
    con = duckdb.connect(DB)
    outs = ",".join(f"'{e}'" for e in OUT_EVENTS)
    con.execute(f"""
        CREATE OR REPLACE TABLE matchup_outcomes AS
        WITH pa AS (
          SELECT e.events, e.season,
                 pit.cluster_v2 AS p_cl, bat.cluster_v2 AS b_cl
          FROM pa_events_reg e
          JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
          JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
          WHERE pit.cluster_v2 IS NOT NULL AND bat.cluster_v2 IS NOT NULL
        )
        SELECT p_cl AS pitcher_cluster, b_cl AS batter_cluster,
          count(*) AS n_pa,
          count(*) FILTER (WHERE events LIKE 'strikeout%')                AS n_k,
          count(*) FILTER (WHERE events='walk')                          AS n_bb,
          count(*) FILTER (WHERE events='intent_walk')                   AS n_ibb,
          count(*) FILTER (WHERE events='hit_by_pitch')                  AS n_hbp,
          count(*) FILTER (WHERE events='home_run')                      AS n_hr,
          count(*) FILTER (WHERE events='single')                        AS n_1b,
          count(*) FILTER (WHERE events='double')                        AS n_2b,
          count(*) FILTER (WHERE events='triple')                        AS n_3b,
          count(*) FILTER (WHERE events IN ('sac_fly','sac_fly_double_play')) AS n_sf,
          count(*) FILTER (WHERE events IN ('sac_bunt'))                 AS n_sh,
          count(*) FILTER (WHERE events IN ({outs}))                     AS n_out,
          count(*) FILTER (WHERE events NOT LIKE 'strikeout%'
                 AND events NOT IN ('walk','intent_walk','hit_by_pitch','home_run',
                     'single','double','triple','sac_fly','sac_fly_double_play',
                     'sac_bunt',{outs}))                                 AS n_other
        FROM pa GROUP BY 1,2
    """)

    con.execute(f"""
        CREATE OR REPLACE VIEW matchup_rates AS
        SELECT pl.rank AS p_rank, pl.label AS pitcher_type,
               bl.rank AS b_rank, bl.label AS batter_type,
               m.pitcher_cluster, m.batter_cluster, m.n_pa,
               round(n_k ::DOUBLE/n_pa, 4) AS k_pct,
               round(n_bb::DOUBLE/n_pa, 4) AS bb_pct,
               round(n_hr::DOUBLE/n_pa, 4) AS hr_pct,
               round((n_1b+n_2b+n_3b+n_hr)::DOUBLE/n_pa, 4) AS hit_pct,
               round((n_2b+n_3b+n_hr)   ::DOUBLE/n_pa, 4) AS xbh_pct,
               (n_pa - n_bb - n_ibb - n_hbp - n_sf - n_sh) AS ab,
               round((n_1b+n_2b+n_3b+n_hr)::DOUBLE
                     / nullif(n_pa - n_bb - n_ibb - n_hbp - n_sf - n_sh, 0), 4) AS ba,
               round((n_1b + 2*n_2b + 3*n_3b + 4*n_hr)::DOUBLE
                     / nullif(n_pa - n_bb - n_ibb - n_hbp - n_sf - n_sh, 0), 4) AS slg,
               -- OBP = (H + BB + HBP) / (AB + BB + HBP + SF). The official
               -- denominator excludes sacrifice BUNTS, so AB+BB+HBP+SF = PA - SH.
               round((n_1b + n_2b + n_3b + n_hr + n_bb + n_ibb + n_hbp)::DOUBLE
                     / nullif(n_pa - n_sh, 0), 4) AS obp
        FROM matchup_outcomes m
        JOIN pitcher_archetypes_v2 pl ON pl.season={REF_SEASON} AND pl.cluster=m.pitcher_cluster
        JOIN batter_archetypes_v2  bl ON bl.season={REF_SEASON} AND bl.cluster=m.batter_cluster
    """)

    cells = con.execute("SELECT count(*), sum(n_pa) FROM matchup_outcomes").fetchone()
    print(f"matchup_outcomes: {cells[0]} type-vs-type cells, {cells[1]} pooled PAs")
    base = con.execute("""
        SELECT round(sum(n_k)::DOUBLE/sum(n_pa),4),
               round(sum(n_bb)::DOUBLE/sum(n_pa),4),
               round(sum(n_hr)::DOUBLE/sum(n_pa),4),
               round(sum(n_1b+n_2b+n_3b+n_hr)::DOUBLE/sum(n_pa),4)
        FROM matchup_outcomes
    """).fetchone()
    print(f"pooled baselines  K%={base[0]:.1%}  BB%={base[1]:.1%}  "
          f"HR%={base[2]:.1%}  HIT%={base[3]:.1%}\n")

    print("Most extreme cells (min n_pa 300):")
    for metric in ("k_pct", "hr_pct", "hit_pct", "bb_pct", "obp"):
        hi = con.execute(f"""SELECT pitcher_type,batter_type,{metric},n_pa
            FROM matchup_rates WHERE n_pa>=300 ORDER BY {metric} DESC LIMIT 1""").fetchone()
        lo = con.execute(f"""SELECT pitcher_type,batter_type,{metric},n_pa
            FROM matchup_rates WHERE n_pa>=300 ORDER BY {metric} ASC LIMIT 1""").fetchone()
        print(f"  {metric:8} HIGH {hi[2]:.1%} ({hi[0]} vs {hi[1]}, n={hi[3]})"
              f"   LOW {lo[2]:.1%} ({lo[0]} vs {lo[1]}, n={lo[3]})")
    con.close()


if __name__ == "__main__":
    main()
