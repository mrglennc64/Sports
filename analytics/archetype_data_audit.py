"""
Phase 1: Data Audit for Pitcher-Batter Archetype Model

This script examines the existing DuckDB database to determine:
1. What tables/features are available
2. Date range coverage
3. Sample sizes per player
4. Missing data patterns
5. Feasibility of building archetype clusters

Run from mlb-edge/:
    python analytics/archetype_data_audit.py
"""

import duckdb
import pandas as pd
import sys
from pathlib import Path

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)

# Connect to database
DB_PATH = 'data/baseball.duckdb'
if not Path(DB_PATH).exists():
    print(f"ERROR: Database not found at {DB_PATH}")
    sys.exit(1)

con = duckdb.connect(DB_PATH, read_only=True)

print("=" * 100)
print("ARCHETYPE MODEL DATA AUDIT")
print("=" * 100)

# ========================================
# 1. CATALOG: What tables exist?
# ========================================
print("\n[1] DATABASE CATALOG")
print("-" * 100)

tables = con.execute("SHOW TABLES").fetchdf()
print(f"Found {len(tables)} tables:")
for idx, row in tables.iterrows():
    table_name = row['name']
    row_count = con.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()[0]
    print(f"  - {table_name:30s} ({row_count:,} rows)")

# ========================================
# 2. SCHEMA: What columns exist in key tables?
# ========================================
print("\n[2] SCHEMA INSPECTION")
print("-" * 100)

key_tables = ['pa_events', 'pitchers', 'batters', 'pitcher_statcast', 'batter_statcast']

for table in key_tables:
    try:
        schema = con.execute(f"DESCRIBE {table}").fetchdf()
        print(f"\n{table} ({len(schema)} columns):")
        print(schema.to_string(index=False))
    except Exception as e:
        print(f"\n{table}: NOT FOUND ({e})")

# ========================================
# 3. DATE RANGE: What years are covered?
# ========================================
print("\n[3] DATE COVERAGE")
print("-" * 100)

try:
    date_range = con.execute("""
        SELECT
            MIN(game_date) as first_date,
            MAX(game_date) as last_date,
            COUNT(DISTINCT game_date) as n_days,
            COUNT(DISTINCT YEAR(game_date)) as n_years,
            COUNT(*) as total_pa
        FROM pa_events
    """).fetchdf()

    print("pa_events:")
    print(date_range.to_string(index=False))

    # Breakdown by year
    by_year = con.execute("""
        SELECT
            YEAR(game_date) as year,
            COUNT(*) as pa_count,
            COUNT(DISTINCT pitcher_id) as n_pitchers,
            COUNT(DISTINCT batter_id) as n_batters,
            COUNT(DISTINCT game_pk) as n_games
        FROM pa_events
        GROUP BY YEAR(game_date)
        ORDER BY year
    """).fetchdf()

    print("\nBreakdown by year:")
    print(by_year.to_string(index=False))

except Exception as e:
    print(f"ERROR querying pa_events: {e}")

# ========================================
# 4. SAMPLE SIZES: How many PAs per player?
# ========================================
print("\n[4] SAMPLE SIZE DISTRIBUTION")
print("-" * 100)

try:
    # Pitcher sample sizes
    pitcher_samples = con.execute("""
        SELECT
            COUNT(*) as n_pitchers,
            MIN(bf) as min_bf,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY bf) as p25_bf,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY bf) as median_bf,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY bf) as p75_bf,
            MAX(bf) as max_bf
        FROM (
            SELECT pitcher_id, COUNT(*) as bf
            FROM pa_events
            WHERE game_date >= '2020-01-01'
            GROUP BY pitcher_id
        )
    """).fetchdf()

    print("Pitcher batters faced (2020+):")
    print(pitcher_samples.to_string(index=False))

    # Batter sample sizes
    batter_samples = con.execute("""
        SELECT
            COUNT(*) as n_batters,
            MIN(pa) as min_pa,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pa) as p25_pa,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pa) as median_pa,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pa) as p75_pa,
            MAX(pa) as max_pa
        FROM (
            SELECT batter_id, COUNT(*) as pa
            FROM pa_events
            WHERE game_date >= '2020-01-01'
            GROUP BY batter_id
        )
    """).fetchdf()

    print("\nBatter plate appearances (2020+):")
    print(batter_samples.to_string(index=False))

    # How many qualify for clustering? (e.g. >=200 BF/PA)
    qualified_pitchers = con.execute("""
        SELECT COUNT(*) as n
        FROM (
            SELECT pitcher_id, COUNT(*) as bf
            FROM pa_events
            WHERE game_date >= '2020-01-01'
            GROUP BY pitcher_id
            HAVING COUNT(*) >= 200
        )
    """).fetchone()[0]

    qualified_batters = con.execute("""
        SELECT COUNT(*) as n
        FROM (
            SELECT batter_id, COUNT(*) as pa
            FROM pa_events
            WHERE game_date >= '2020-01-01'
            GROUP BY batter_id
            HAVING COUNT(*) >= 150
        )
    """).fetchone()[0]

    print(f"\nQualified for clustering (2020+):")
    print(f"  Pitchers (>=200 BF): {qualified_pitchers}")
    print(f"  Batters (>=150 PA):  {qualified_batters}")

except Exception as e:
    print(f"ERROR: {e}")

# ========================================
# 5. AVAILABLE FEATURES: What can we use for clustering?
# ========================================
print("\n[5] CLUSTERING FEATURE AVAILABILITY")
print("-" * 100)

# Check what outcome/event columns exist
try:
    sample_pa = con.execute("SELECT * FROM pa_events LIMIT 1").fetchdf()
    available_cols = sample_pa.columns.tolist()

    # Core features for clustering
    pitcher_feature_candidates = [
        'release_speed', 'effective_speed', 'release_spin_rate',
        'pitch_type', 'pfx_x', 'pfx_z', 'plate_x', 'plate_z',
        'vx0', 'vy0', 'vz0', 'ax', 'ay', 'az',
        'sz_top', 'sz_bot', 'hit_distance_sc', 'launch_speed',
        'launch_angle', 'bb_type', 'events', 'description'
    ]

    batter_feature_candidates = [
        'launch_speed', 'launch_angle', 'hit_distance_sc',
        'bb_type', 'stand', 'events'
    ]

    print("Columns available in pa_events:")
    print(f"  Total columns: {len(available_cols)}")

    print("\nPotential pitcher clustering features:")
    for feat in pitcher_feature_candidates:
        if feat in available_cols:
            # Check null %
            null_pct = con.execute(f"""
                SELECT
                    100.0 * SUM(CASE WHEN {feat} IS NULL THEN 1 ELSE 0 END) / COUNT(*) as null_pct
                FROM pa_events
                WHERE game_date >= '2020-01-01'
            """).fetchone()[0]
            print(f"  ✓ {feat:25s} (null: {null_pct:5.1f}%)")
        else:
            print(f"  ✗ {feat:25s} (NOT FOUND)")

    print("\nPotential batter clustering features:")
    for feat in batter_feature_candidates:
        if feat in available_cols:
            null_pct = con.execute(f"""
                SELECT
                    100.0 * SUM(CASE WHEN {feat} IS NULL THEN 1 ELSE 0 END) / COUNT(*) as null_pct
                FROM pa_events
                WHERE game_date >= '2020-01-01'
            """).fetchone()[0]
            print(f"  ✓ {feat:25s} (null: {null_pct:5.1f}%)")
        else:
            print(f"  ✗ {feat:25s} (NOT FOUND)")

except Exception as e:
    print(f"ERROR: {e}")

# ========================================
# 6. RATE STATS: Can we compute K%, BB%, etc?
# ========================================
print("\n[6] RATE STAT COMPUTATION TEST")
print("-" * 100)

try:
    # Check what event types exist
    event_types = con.execute("""
        SELECT events, COUNT(*) as cnt
        FROM pa_events
        WHERE game_date >= '2020-01-01' AND events IS NOT NULL
        GROUP BY events
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchdf()

    print("Top event types in pa_events:")
    print(event_types.to_string(index=False))

    # Test computing K%, BB% for a sample pitcher
    sample_pitcher_stats = con.execute("""
        SELECT
            pitcher_id,
            COUNT(*) as bf,
            SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as k_count,
            SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) as bb_count,
            100.0 * SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) / COUNT(*) as k_pct,
            100.0 * SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) / COUNT(*) as bb_pct
        FROM pa_events
        WHERE game_date >= '2020-01-01'
        GROUP BY pitcher_id
        HAVING COUNT(*) >= 500
        ORDER BY bf DESC
        LIMIT 5
    """).fetchdf()

    print("\nSample pitcher rate stats (top 5 by BF):")
    print(sample_pitcher_stats.to_string(index=False))

except Exception as e:
    print(f"ERROR: {e}")

# ========================================
# 7. MISSING DATA PATTERNS
# ========================================
print("\n[7] MISSING DATA PATTERNS")
print("-" * 100)

try:
    # Check nulls in key columns
    null_check = con.execute("""
        SELECT
            COUNT(*) as total_rows,
            SUM(CASE WHEN pitcher_id IS NULL THEN 1 ELSE 0 END) as pitcher_id_null,
            SUM(CASE WHEN batter_id IS NULL THEN 1 ELSE 0 END) as batter_id_null,
            SUM(CASE WHEN events IS NULL THEN 1 ELSE 0 END) as events_null,
            SUM(CASE WHEN release_speed IS NULL THEN 1 ELSE 0 END) as velo_null,
            SUM(CASE WHEN launch_speed IS NULL THEN 1 ELSE 0 END) as exit_velo_null,
            SUM(CASE WHEN bb_type IS NULL THEN 1 ELSE 0 END) as bb_type_null
        FROM pa_events
        WHERE game_date >= '2020-01-01'
    """).fetchdf()

    print("Null counts (2020+):")
    print(null_check.to_string(index=False))

    # Null percentages
    total = null_check['total_rows'].values[0]
    print("\nNull percentages:")
    for col in null_check.columns:
        if col != 'total_rows':
            pct = 100.0 * null_check[col].values[0] / total
            print(f"  {col:20s}: {pct:5.1f}%")

except Exception as e:
    print(f"ERROR: {e}")

# ========================================
# 8. SUMMARY & RECOMMENDATIONS
# ========================================
print("\n[8] SUMMARY & RECOMMENDATIONS")
print("-" * 100)

print("""
Based on this audit, here are the next steps:

1. If pa_events has pitcher_id, batter_id, events, and date columns:
   ✓ You can proceed to Phase 2 (feature engineering)

2. Recommended clustering features (based on availability):
   - Pitchers: K%, BB%, HR%, GB%, FB%, avg velo (if available)
   - Batters: K%, BB%, ISO, exit velo, launch angle distribution

3. Suggested sample filters:
   - Pitchers: >= 200 batters faced (2020+)
   - Batters: >= 150 plate appearances (2020+)

4. Expected archetype count:
   - Pitchers: 4-6 clusters (power arms, control artists, groundballers, etc.)
   - Batters: 4-6 clusters (sluggers, contact hitters, patient veterans, etc.)

5. Interaction matrix feasibility:
   - With 5 pitcher × 5 batter archetypes = 25 cells
   - Need ~50+ PAs per cell for stable estimates
   - Total PAs needed: 25 × 50 = 1,250 minimum

6. If key columns are missing:
   - Check if pitcher_statcast / batter_statcast tables have aggregated stats
   - May need to compute rate stats first, then join to pa_events

Ready to proceed to Phase 2: Feature Engineering
""")

# Save audit results to file
audit_output = Path('analytics/archetype_audit_results.txt')
print(f"\nSaving detailed audit to: {audit_output}")

con.close()
