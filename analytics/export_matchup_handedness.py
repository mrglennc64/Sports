"""Second view — HANDEDNESS / platoon matchup matrix (rule-based groups).

The data-driven cluster matrix (export_matchup_csv.py) ignores handedness, yet the
L/R platoon split is the single most established edge in baseball. This view groups
players by simple, transparent RULES instead of clustering:

  Pitchers (from pitchers.throws / k_pct / go_ao):
    GB_specialist            go_ao >= 1.5 (strong ground-ball lean, any hand)
    RHP_power / RHP_finesse  throws=R, K% >= / < the starter median
    LHP_power / LHP_finesse  throws=L, K% >= / < the starter median
  Batters (from batters.bats / iso):
    SH_switch                bats=S
    RHB_power / RHB_contact  bats=R, ISO >= / < the qualified-batter median
    LHB_power / LHB_contact  bats=L, ISO >= / < the median

Thresholds are data-driven medians so the power/finesse and power/contact splits
are balanced. Same stat set + CSV schema as the cluster view, written to
../data/matchup_matrix_handedness.csv. Pools 2024-2026 regular season.

    python export_matchup_handedness.py
"""
from __future__ import annotations

import csv

import duckdb

DB = "../data/baseball.duckdb"
OUT_CSV = "../data/matchup_matrix_handedness.csv"
MIN_PA = 100

HEADER = ["pitcher_group", "batter_group", "PA", "AVG", "OBP", "SLG", "wOBA",
          "K_rate", "BB_rate", "GB_rate", "FB_rate", "HardHit_rate"]


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    pk = con.execute("SELECT median(k_pct) FROM pitchers "
                     "WHERE season IN (2024,2025,2026) AND ip>=30").fetchone()[0]
    bi = con.execute("SELECT median(iso) FROM batters "
                     "WHERE season IN (2024,2025,2026) AND pa>=100").fetchone()[0]
    print(f"thresholds: pitcher K% median={pk:.3f}  batter ISO median={bi:.3f}")

    rows = con.execute(f"""
        WITH pa AS (
          SELECT e.events, e.bb_type, e.launch_speed,
            CASE
              WHEN pit.throws IS NULL THEN NULL
              WHEN pit.go_ao >= 1.5 THEN 'GB_specialist'
              WHEN pit.throws='R' AND pit.k_pct >= {pk} THEN 'RHP_power'
              WHEN pit.throws='R' THEN 'RHP_finesse'
              WHEN pit.throws='L' AND pit.k_pct >= {pk} THEN 'LHP_power'
              WHEN pit.throws='L' THEN 'LHP_finesse'
            END AS p_grp,
            CASE
              WHEN bat.bats IS NULL THEN NULL
              WHEN bat.bats='S' THEN 'SH_switch'
              WHEN bat.bats='R' AND bat.iso >= {bi} THEN 'RHB_power'
              WHEN bat.bats='R' THEN 'RHB_contact'
              WHEN bat.bats='L' AND bat.iso >= {bi} THEN 'LHB_power'
              WHEN bat.bats='L' THEN 'LHB_contact'
            END AS b_grp
          FROM pa_events_reg e
          JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
          JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
        ),
        cell AS (
          SELECT p_grp, b_grp,
            count(*) AS pa,
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
            count(*) FILTER (WHERE bb_type IN ('ground_ball','fly_ball','line_drive','popup')) AS bip,
            count(*) FILTER (WHERE bb_type='ground_ball')              AS gb,
            count(*) FILTER (WHERE bb_type='fly_ball')                 AS fb,
            count(*) FILTER (WHERE launch_speed IS NOT NULL)           AS bbe,
            count(*) FILTER (WHERE launch_speed >= 95)                 AS hardhit
          FROM pa WHERE p_grp IS NOT NULL AND b_grp IS NOT NULL
          GROUP BY p_grp, b_grp
        )
        SELECT p_grp, b_grp, pa,
          round((b1+b2+b3+hr)::DOUBLE / nullif(pa-ubb-ibb-hbp-sf-sh,0), 3)            AS avg,
          round((b1+b2+b3+hr+ubb+ibb+hbp)::DOUBLE / nullif(pa-sh,0), 3)               AS obp,
          round((b1+2*b2+3*b3+4*hr)::DOUBLE / nullif(pa-ubb-ibb-hbp-sf-sh,0), 3)      AS slg,
          round((0.69*ubb+0.72*hbp+0.89*b1+1.27*b2+1.62*b3+2.10*hr)
                / nullif((pa-ubb-ibb-hbp-sf-sh)+ubb+sf+hbp,0), 3)                     AS woba,
          round(k::DOUBLE/nullif(pa,0), 3)                                           AS k_rate,
          round(ubb::DOUBLE/nullif(pa,0), 3)                                         AS bb_rate,
          round(gb::DOUBLE/nullif(bip,0), 3)                                         AS gb_rate,
          round(fb::DOUBLE/nullif(bip,0), 3)                                         AS fb_rate,
          round(hardhit::DOUBLE/nullif(bbe,0), 3)                                    AS hardhit_rate
        FROM cell WHERE pa >= {MIN_PA}
        ORDER BY p_grp, b_grp
    """).fetchall()
    con.close()

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r[0], r[1], int(r[2]), *r[3:]])

    print(f"wrote {len(rows)} cells to {OUT_CSV}  (total PA {sum(int(r[2]) for r in rows)})")
    rated = sorted([r for r in rows if r[6] is not None], key=lambda r: r[6])
    print("lowest wOBA:")
    for r in rated[:3]:
        print(f"  {r[6]:.3f}  {r[0]} vs {r[1]}  (PA={int(r[2])})")
    print("highest wOBA:")
    for r in reversed(rated[-3:]):
        print(f"  {r[6]:.3f}  {r[0]} vs {r[1]}  (PA={int(r[2])})")


if __name__ == "__main__":
    main()
