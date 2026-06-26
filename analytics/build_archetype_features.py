"""
Build archetype features for pitcher and batter clustering.

Aggregates stats from 2024-2026 seasons and joins with Statcast data
to create comprehensive feature sets for archetype identification.
"""

import duckdb
import pandas as pd
from pathlib import Path


def build_pitcher_features(conn):
    """Build aggregated pitcher features for clustering."""

    query = """
    WITH pitcher_base AS (
        SELECT
            p.player_id,
            p.name,
            p.throws,
            SUM(p.bf) as total_bf,
            -- Weighted averages by BF
            SUM(p.so) * 100.0 / NULLIF(SUM(p.bf), 0) as k_pct,
            SUM(p.bb) * 100.0 / NULLIF(SUM(p.bf), 0) as bb_pct,
            SUM(p.hr) * 9.0 / NULLIF(SUM(p.ip), 0) as hr_per_9,
            -- Ground ball / fly ball percentages
            SUM(p.ground_outs) * 100.0 / NULLIF(SUM(p.ground_outs + p.air_outs), 0) as gb_pct,
            SUM(p.air_outs) * 100.0 / NULLIF(SUM(p.ground_outs + p.air_outs), 0) as fb_pct,
            SUM(p.ip) as total_ip,
            SUM(p.so) as total_so,
            SUM(p.bb) as total_bb,
            SUM(p.hr) as total_hr
        FROM pitchers p
        WHERE p.season >= 2024
        GROUP BY p.player_id, p.name, p.throws
        HAVING SUM(p.bf) >= 200
    ),
    pitcher_statcast_agg AS (
        SELECT
            ps.player_id,
            -- Weighted averages by PA
            SUM(ps.pa * ps.whiff_percent) / NULLIF(SUM(ps.pa), 0) as whiff_pct,
            SUM(ps.pa * ps.fastball_avg_speed) / NULLIF(SUM(ps.pa), 0) as avg_velo,
            SUM(ps.pa * ps.barrel_batted_rate) / NULLIF(SUM(ps.pa), 0) as barrel_pct,
            SUM(ps.pa * ps.exit_velocity_avg) / NULLIF(SUM(ps.pa), 0) as exit_velo_allowed,
            SUM(ps.pa * ps.hard_hit_percent) / NULLIF(SUM(ps.pa), 0) as hard_hit_allowed,
            SUM(ps.pa * ps.groundballs_percent) / NULLIF(SUM(ps.pa), 0) as gb_pct_statcast
        FROM pitcher_statcast ps
        WHERE ps.season >= 2024
        GROUP BY ps.player_id
    )
    SELECT
        pb.player_id,
        pb.name,
        pb.throws,
        pb.total_bf,
        pb.k_pct,
        pb.bb_pct,
        pb.hr_per_9,
        pb.gb_pct,
        pb.fb_pct,
        psa.whiff_pct,
        psa.avg_velo,
        psa.barrel_pct,
        psa.exit_velo_allowed,
        psa.hard_hit_allowed,
        psa.gb_pct_statcast
    FROM pitcher_base pb
    LEFT JOIN pitcher_statcast_agg psa ON pb.player_id = psa.player_id
    ORDER BY pb.total_bf DESC
    """

    return conn.execute(query).df()


def build_batter_features(conn):
    """Build aggregated batter features for clustering."""

    query = """
    WITH batter_base AS (
        SELECT
            b.player_id,
            b.name,
            b.bats,
            SUM(b.pa) as total_pa,
            -- Weighted averages by PA
            SUM(b.so) * 100.0 / NULLIF(SUM(b.pa), 0) as k_pct,
            SUM(b.bb) * 100.0 / NULLIF(SUM(b.pa), 0) as bb_pct,
            -- ISO = (2B + 2*3B + 3*HR) / AB
            (SUM(b.doubles) + 2*SUM(b.triples) + 3*SUM(b.hr)) * 1.0 / NULLIF(SUM(b.ab), 0) as iso,
            SUM(b.ab) as total_ab,
            SUM(b.hr) as total_hr,
            SUM(b.bb) as total_bb,
            SUM(b.so) as total_so
        FROM batters b
        WHERE b.season >= 2024
        GROUP BY b.player_id, b.name, b.bats
        HAVING SUM(b.pa) >= 150
    ),
    batter_statcast_agg AS (
        SELECT
            bs.player_id,
            -- Weighted averages by PA
            SUM(bs.pa * bs.exit_velocity_avg) / NULLIF(SUM(bs.pa), 0) as exit_velo,
            SUM(bs.pa * bs.launch_angle_avg) / NULLIF(SUM(bs.pa), 0) as launch_angle,
            SUM(bs.pa * bs.hard_hit_percent) / NULLIF(SUM(bs.pa), 0) as hard_hit_pct,
            SUM(bs.pa * bs.barrel_batted_rate) / NULLIF(SUM(bs.pa), 0) as barrel_pct,
            SUM(bs.pa * bs.whiff_percent) / NULLIF(SUM(bs.pa), 0) as whiff_pct,
            SUM(bs.pa * bs.sweet_spot_percent) / NULLIF(SUM(bs.pa), 0) as sweet_spot_pct
        FROM batter_statcast bs
        WHERE bs.season >= 2024
        GROUP BY bs.player_id
    )
    SELECT
        bb.player_id,
        bb.name,
        bb.bats,
        bb.total_pa,
        bb.k_pct,
        bb.bb_pct,
        bb.iso,
        bsa.exit_velo,
        bsa.launch_angle,
        bsa.hard_hit_pct,
        bsa.barrel_pct,
        bsa.whiff_pct,
        bsa.sweet_spot_pct
    FROM batter_base bb
    LEFT JOIN batter_statcast_agg bsa ON bb.player_id = bsa.player_id
    ORDER BY bb.total_pa DESC
    """

    return conn.execute(query).df()


def report_feature_completeness(df, feature_type):
    """Report on feature completeness and distributions."""

    print(f"\n{'='*60}")
    print(f"{feature_type.upper()} FEATURES REPORT")
    print(f"{'='*60}")

    print(f"\nTotal rows: {len(df)}")

    # Feature completeness
    print(f"\n--- Feature Completeness (% non-null) ---")
    completeness = (df.notna().sum() / len(df) * 100).sort_values(ascending=False)
    for col, pct in completeness.items():
        status = "[OK]" if pct == 100 else "[WARN]" if pct >= 90 else "[MISS]"
        print(f"{status} {col:25s}: {pct:6.2f}%")

    # Numeric columns only
    numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns
    numeric_cols = [col for col in numeric_cols if col not in ['player_id', 'total_bf', 'total_pa', 'total_ab']]

    if len(numeric_cols) > 0:
        print(f"\n--- Distribution Stats (key features) ---")
        stats = df[numeric_cols].describe()
        print(stats.round(2))

    # Check for missing Statcast data
    statcast_cols = [col for col in df.columns if col not in ['player_id', 'name', 'throws', 'bats', 'total_bf', 'total_pa', 'total_ab', 'k_pct', 'bb_pct', 'hr_per_9', 'gb_pct', 'fb_pct', 'iso']]
    if statcast_cols:
        missing_statcast = df[statcast_cols].isna().all(axis=1).sum()
        print(f"\n--- Statcast Coverage ---")
        print(f"Players missing ALL Statcast data: {missing_statcast} ({missing_statcast/len(df)*100:.1f}%)")
        print(f"Players with ANY Statcast data: {len(df) - missing_statcast} ({(len(df)-missing_statcast)/len(df)*100:.1f}%)")


def main():
    # Connect to database
    db_path = Path(__file__).parent.parent / "data" / "baseball.duckdb"
    conn = duckdb.connect(str(db_path), read_only=True)

    # Create exports directory
    export_dir = Path(__file__).parent.parent / "data" / "exports"
    export_dir.mkdir(exist_ok=True)

    print("Building pitcher archetype features...")
    pitcher_df = build_pitcher_features(conn)

    print("Building batter archetype features...")
    batter_df = build_batter_features(conn)

    # Save to CSV
    pitcher_path = export_dir / "pitcher_archetype_features.csv"
    batter_path = export_dir / "batter_archetype_features.csv"

    pitcher_df.to_csv(pitcher_path, index=False)
    batter_df.to_csv(batter_path, index=False)

    print(f"\nSaved {len(pitcher_df)} pitchers to: {pitcher_path}")
    print(f"Saved {len(batter_df)} batters to: {batter_path}")

    # Report statistics
    report_feature_completeness(pitcher_df, "pitcher")
    report_feature_completeness(batter_df, "batter")

    conn.close()


if __name__ == "__main__":
    main()
