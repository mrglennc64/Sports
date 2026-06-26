"""
Phase 1: Data Audit for Pitcher-Batter Archetype Model (Fixed)

Run from mlb-edge/:
    python analytics/archetype_data_audit_v2.py
"""

import duckdb
import pandas as pd
import sys
from pathlib import Path

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

print("\n[1] DATE COVERAGE")
print("-" * 100)

date_range = con.execute("""
    SELECT
        MIN(game_date) as first_date,
        MAX(game_date) as last_date,
        COUNT(DISTINCT game_date) as n_days,
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
        COUNT(DISTINCT batter) as n_batters
    FROM pa_events
    GROUP BY EXTRACT(YEAR FROM game_date)
    ORDER BY year
""").fetchdf()

print("\nBy year:")
print(by_year.to_string(index=False))

print("\n[2] SAMPLE SIZE DISTRIBUTION")
print("-" * 100)

pitcher_samples = con.execute("""
    SELECT
        COUNT(*) as n_pitchers,
        MIN(bf) as min_bf,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY bf) as median_bf,
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

print("\n[3] RATE STAT FEASIBILITY")
print("-" * 100)

sample_pitcher_stats = con.execute("""
    SELECT
        pitcher,
        COUNT(*) as bf,
        100.0 * SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) / COUNT(*) as k_pct,
        100.0 * SUM(CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END) / COUNT(*) as bb_pct,
        100.0 * SUM(CASE WHEN events = 'home_run' THEN 1 ELSE 0 END) / COUNT(*) as hr_pct
    FROM pa_events
    WHERE game_date >= '2024-01-01'
    GROUP BY pitcher
    HAVING COUNT(*) >= 500
    ORDER BY bf DESC
    LIMIT 5
""").fetchdf()

print("Sample pitcher rate stats:")
print(sample_pitcher_stats.to_string(index=False))

print("\n[4] SUMMARY")
print("=" * 100)

print(f"""
KEY FINDINGS:

1. DATA COVERAGE: 2024-2026 (recent data only, ~489k PAs)

2. COLUMN NAMES:
   - pa_events uses 'pitcher' and 'batter' (NOT pitcher_id/batter_id)
   - Need to JOIN: pa_events.pitcher = pitchers.player_id

3. QUALIFIED PLAYERS:
   - Pitchers (>=200 BF): {qualified_pitchers}
   - Batters (>=150 PA): {qualified_batters}

4. EXISTING ARCHETYPE TABLES FOUND:
   - pitcher_archetypes_v2 (6 rows)
   - batter_archetypes_v2 (7 rows)

NEXT: Phase 2 - build_archetype_features.py
""")

con.close()
