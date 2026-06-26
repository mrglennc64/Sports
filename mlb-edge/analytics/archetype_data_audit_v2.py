"""
Phase 1: Data Audit for Pitcher-Batter Archetype Model (Fixed)

Run from mlb-edge/:
    python analytics/archetype_data_audit_v2.py
"""

import duckdb
import pandas as pd
import sys
from pathlib import Path

# Fix Windows console encoding
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)

DB_PATH = 'data/baseball.duckdb'
if not Path(DB_PATH).exists():
    print(f"ERROR: Database not found at {DB_PATH}")
    sys.exit(1)

con = duckdb.connect(DB_PATH, read_only=True)

print("=" * 100)
print("ARCHETYPE MODEL DATA AUDIT - CORRECTED")
print("=" * 100)

# ====================================================================================
# KEY FINDING: pa_events uses 'pitcher' and 'batter', NOT 'pitcher_id'/'batter_id'
# ====================================================================================

print("\n[1] DATE COVERAGE")
print("-" * 100)

date_range = con.execute("""
    SELECT
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNT(DISTINCT game_date) as n_days,
        COUNT(DISTINCT EXTRACT(YEAR FROM game_date)) as n_years,
        COUNT(*) as total_pa
    FROM pa_events
""").fetchdf()

print("pa_events coverage:")
print(date_range.to_string(index=False))

by_year = con.execute("""
    SELECT
        EXTRACT(YEAR FROM game_date) as year,
        COUNT(*) as pa_count,
        COUNT(DISTINCT pitcher) as n_pitchers,
        COUNT(DISTINCT batter) as n_batters,
        COUNT(DISTINCT game_pk) as n_games
    FROM pa_events
    GROUP BY EXTRACT(YEAR FROM game_date)
    ORDER BY year
""").fetchdf()

print("\nBy year:")
print(by_year.to_string(index=False))

print("\n[2] SAMPLE SIZE DISTRIBUTION")
print("-" * 100)

# Pitcher sample sizes (using correct column name 'pitcher')
pitcher_samples = con.execute("""
    SELECT
        COUNT(*) as n_pitchers,
        MIN(bf) as min_bf,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY bf) as p25_bf,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY bf) as median_bf,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY bf) as p75_bf,
        MAX(bf) as max_bf
    FROM (
        SELECT pitcher, COUNT(*) as bf
        FROM pa_events
        WHERE game_date >= '2024-01-01'
        GROUP BY pitcher
    )
""").fetchdf()

print("Pitcher batters faced (2024+):")
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
        SELECT batter, COUNT(*) as pa
        FROM pa_events
        WHERE game_date >= '2024-01-01'
        GROUP BY batter
    )
""").fetchdf()

print("\nBatter plate appearances (2024+):")
print(batter_samples.to_string(index=False))

# Qualified players
qualified_pitchers = con.execute("""
    SELECT COUNT(*) as n
    FROM (
        SELECT pitcher, COUNT(*) as bf
        FROM pa_events
        WHERE game_date >= '2024-01-01'
        GROUP BY pitcher
        HAVING COUNT(*) >= 200
    )
""").fetchone()[0]

qualified_batters = con.execute("""
    SELECT COUNT(*) as n
    FROM (
        SELECT batter, COUNT(*) as pa
        FROM pa_events
        WHERE game_date >= '2024-01-01'
        GROUP BY batter
        HAVING COUNT(*) >= 150
    )
""").fetchone()[0]

print(f"\nQualified for clustering (2024+):")
print(f"  Pitchers (>=200 BF): {qualified_pitchers}")
print(f"  Batters (>=150 PA):  {qualified_batters}")

print("\n[3] AVAILABLE FEATURES")
print("-" * 100)

# Check what columns are available in pa_events
sample = con.execute("SELECT * FROM pa_events LIMIT 1").fetchdf()
cols = sample.columns.tolist()

print(f"pa_events has {len(cols)} columns:")
for col in cols:
    print(f"  - {col}")

print("\n[4] RATE STAT FEASIBILITY")
print("-" * 100)

# Test computing K%, BB%, HR% for sample pitchers
sample_pitcher_stats = con.execute("""
    SELECT
        pitcher,
        COUNT(*) as bf,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as k_count,
        SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) as bb_count,
        SUM(CASE WHEN events = 'home_run' THEN 1 ELSE 0 END) as hr_count,
        100.0 * SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) / COUNT(*) as k_pct,
        100.0 * SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) / COUNT(*) as bb_pct,
        100.0 * SUM(CASE WHEN events = 'home_run' THEN 1 ELSE 0 END) / COUNT(*) as hr_pct,
        100.0 * SUM(CASE WHEN bb_type = 'ground_ball' THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN bb_type IS NOT NULL THEN 1 ELSE 0 END), 0) as gb_pct,
        100.0 * SUM(CASE WHEN bb_type = 'fly_ball' THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN bb_type IS NOT NULL THEN 1 ELSE 0 END), 0) as fb_pct
    FROM pa_events
    WHERE game_date >= '2024-01-01'
    GROUP BY pitcher
    HAVING COUNT(*) >= 500
    ORDER BY bf DESC
    LIMIT 5
""").fetchdf()

print("Sample pitcher rate stats (top 5 by BF, 2024+):")
print(sample_pitcher_stats.to_string(index=False))

# Same for batters
sample_batter_stats = con.execute("""
    SELECT
        batter,
        COUNT(*) as pa,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as k_count,
        SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) as bb_count,
        100.0 * SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) / COUNT(*) as k_pct,
        100.0 * SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) / COUNT(*) as bb_pct,
        AVG(launch_speed) as avg_exit_velo,
        AVG(launch_angle) as avg_launch_angle
    FROM pa_events
    WHERE game_date >= '2024-01-01'
    GROUP BY batter
    HAVING COUNT(*) >= 300
    ORDER BY pa DESC
    LIMIT 5
""").fetchdf()

print("\nSample batter stats (top 5 by PA, 2024+):")
print(sample_batter_stats.to_string(index=False))

print("\n[5] MISSING DATA PATTERNS")
print("-" * 100)

null_check = con.execute("""
    SELECT
        COUNT(*) as total_rows,
        SUM(CASE WHEN pitcher IS NULL THEN 1 ELSE 0 END) as pitcher_null,
        SUM(CASE WHEN batter IS NULL THEN 1 ELSE 0 END) as batter_null,
        SUM(CASE WHEN events IS NULL THEN 1 ELSE 0 END) as events_null,
        SUM(CASE WHEN bb_type IS NULL THEN 1 ELSE 0 END) as bb_type_null,
        SUM(CASE WHEN launch_speed IS NULL THEN 1 ELSE 0 END) as exit_velo_null,
        SUM(CASE WHEN launch_angle IS NULL THEN 1 ELSE 0 END) as launch_angle_null
    FROM pa_events
    WHERE game_date >= '2024-01-01'
""").fetchdf()

print("Null counts (2024+):")
total = null_check['total_rows'].values[0]
for col in null_check.columns:
    if col != 'total_rows':
        count = null_check[col].values[0]
        pct = 100.0 * count / total
        print(f"  {col:20s}: {count:8,} ({pct:5.1f}%)")

print("\n[6] EXISTING PITCHER/BATTER TABLES")
print("-" * 100)

# Check if pitchers/batters tables have pre-computed stats
pitchers_sample = con.execute("SELECT * FROM pitchers LIMIT 3").fetchdf()
print("pitchers table sample:")
print(pitchers_sample[['player_id', 'name', 'season', 'bf', 'k_pct', 'bb_pct', 'hr_per_9']].to_string(index=False))

batters_sample = con.execute("SELECT * FROM batters LIMIT 3").fetchdf()
print("\nbatters table sample:")
print(batters_sample[['player_id', 'name', 'season', 'pa', 'k_pct', 'bb_pct', 'avg', 'obp']].to_string(index=False))

# Check if pitcher_statcast / batter_statcast exist
print("\n[7] STATCAST TABLES")
print("-" * 100)

pitcher_statcast_sample = con.execute("SELECT * FROM pitcher_statcast LIMIT 3").fetchdf()
print("pitcher_statcast sample:")
print(pitcher_statcast_sample.to_string(index=False))

batter_statcast_sample = con.execute("SELECT * FROM batter_statcast LIMIT 3").fetchdf()
print("\nbatter_statcast sample:")
print(batter_statcast_sample.to_string(index=False))

print("\n[8] SUMMARY & NEXT STEPS")
print("=" * 100)

print("""
KEY FINDINGS:

1. DATA COVERAGE:
   - Date range: 2024-03-15 to 2026-06-14 (recent data only!)
   - Total PAs: ~489,000
   - This is RECENT data (2024-2026), NOT historical 2012-2022

2. COLUMN NAMES (CRITICAL):
   - pa_events uses 'pitcher' and 'batter' (NOT pitcher_id/batter_id)
   - pitchers/batters tables use 'player_id' for the ID column
   - Need to JOIN: pa_events.pitcher = pitchers.player_id

3. AVAILABLE FOR CLUSTERING:
   - Pitchers (>=200 BF): """ + str(qualified_pitchers) + """
   - Batters (>=150 PA): """ + str(qualified_batters) + """

4. EXISTING ARCHETYPE TABLES:
   - pitcher_archetypes_v2 (6 rows) - ALREADY EXISTS!
   - batter_archetypes_v2 (7 rows) - ALREADY EXISTS!
   - May want to use these OR rebuild from scratch

5. FEATURE OPTIONS:

   Option A: Use pre-computed stats from pitchers/batters tables
   - Has: k_pct, bb_pct, hr_per_9, etc.
   - Pro: Clean, already aggregated
   - Con: Season-level only

   Option B: Compute from pa_events
   - Has: raw outcomes, bb_type, launch_speed, launch_angle
   - Pro: Can control date range, filters
   - Con: Missing data in Statcast columns (~60-70% null)

   Option C: Use pitcher_statcast / batter_statcast tables
   - Has: whiff%, swing%, exit velo, barrel%, etc.
   - Pro: Rich Statcast metrics
   - Con: Only """ + str(len(con.execute("SELECT DISTINCT player_id FROM pitcher_statcast").fetchdf())) + """ pitchers, """ + str(len(con.execute("SELECT DISTINCT player_id FROM batter_statcast").fetchdf())) + """ batters

RECOMMENDATION:
- Use Option A (pitchers/batters tables) for Phase 2
- Supplement with Statcast where available (Option C)
- Focus on 2024-2026 data (what you have)

NEXT: Phase 2 - Feature Engineering
  python analytics/build_archetype_features.py
""")

con.close()
