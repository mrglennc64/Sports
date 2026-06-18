"""Third view — APPROACH/PROFILE matchup matrix (pitch-mix x spray).

Completes the taxonomy from the user's spec using the newly-pulled free Savant
fields (no Camoufox/FanGraphs needed):
  Pitchers by PITCH MIX (pitcher_arsenal.fastball_pct):
    fastball_power   fastball% >= 60
    mixed            45-60
    soft_breaking    < 45   (the "offspeed/breaking-dominant" type)
  Batters by SPRAY (batter_statcast pull/opposite_percent):
    pull_heavy       pull% >= 45
    opposite_field   oppo% >= 27
    spray_neutral    otherwise

Same stat set/schema as the other views -> ../data/matchup_matrix_profile.csv.
Coverage = qualified players (Savant min thresholds), pooled 2024-2026.

    python export_matchup_profile.py
"""
from __future__ import annotations

import csv

import duckdb

DB = "../data/baseball.duckdb"
OUT_CSV = "../data/matchup_matrix_profile.csv"
MIN_PA = 100

HEADER = ["pitcher_group", "batter_group", "PA", "AVG", "OBP", "SLG", "wOBA",
          "K_rate", "BB_rate", "GB_rate", "FB_rate", "HardHit_rate"]


def main() -> None:
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute(f"""
        WITH pa AS (
          SELECT e.events, e.bb_type, e.launch_speed,
            CASE WHEN ars.fastball_pct >= 60 THEN 'fastball_power'
                 WHEN ars.fastball_pct <  45 THEN 'soft_breaking'
                 ELSE 'mixed' END AS p_grp,
            CASE WHEN bs.pull_percent     >= 45 THEN 'pull_heavy'
                 WHEN bs.opposite_percent >= 27 THEN 'opposite_field'
                 ELSE 'spray_neutral' END AS b_grp
          FROM pa_events_reg e
          JOIN pitcher_arsenal ars ON ars.player_id=e.pitcher AND ars.season=e.season
          JOIN batter_statcast bs  ON bs.player_id=e.batter   AND bs.season=e.season
          WHERE ars.fastball_pct IS NOT NULL AND bs.pull_percent IS NOT NULL
        ),
        cell AS (
          SELECT p_grp, b_grp, count(*) AS pa,
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
          FROM pa GROUP BY p_grp, b_grp
        )
        SELECT p_grp, b_grp, pa,
          round((b1+b2+b3+hr)::DOUBLE / nullif(pa-ubb-ibb-hbp-sf-sh,0), 3)            AS avg,
          round((b1+b2+b3+hr+ubb+ibb+hbp)::DOUBLE / nullif(pa-sh,0), 3)               AS obp,
          round((b1+2*b2+3*b3+4*hr)::DOUBLE / nullif(pa-ubb-ibb-hbp-sf-sh,0), 3)      AS slg,
          round((0.69*ubb+0.72*hbp+0.89*b1+1.27*b2+1.62*b3+2.10*hr)
                / nullif((pa-ubb-ibb-hbp-sf-sh)+ubb+sf+hbp,0), 3)                     AS woba,
          round(k::DOUBLE/nullif(pa,0), 3)        AS k_rate,
          round(ubb::DOUBLE/nullif(pa,0), 3)      AS bb_rate,
          round(gb::DOUBLE/nullif(bip,0), 3)      AS gb_rate,
          round(fb::DOUBLE/nullif(bip,0), 3)      AS fb_rate,
          round(hardhit::DOUBLE/nullif(bbe,0), 3) AS hardhit_rate
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
    print(f"\n{'pitcher':16}{'batter':16}{'PA':>7}{'wOBA':>7}{'K%':>7}{'HardHit%':>9}")
    for r in rows:
        print(f"{r[0]:16}{r[1]:16}{int(r[2]):>7}{r[6]:>7.3f}{r[7]:>7.3f}{r[11]:>9.3f}")


if __name__ == "__main__":
    main()
