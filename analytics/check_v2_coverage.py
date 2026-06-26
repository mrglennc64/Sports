"""Check V2 pitcher baseline coverage on June 1-14 backtest"""

import sys
sys.path.append('backend')
import duckdb
from app.models.archetype_predictor_v2 import ArchetypePredictorV2

# Load V2 predictor
print("Loading V2 predictor...")
v2 = ArchetypePredictorV2()

# Get all unique pitchers from June 1-14
con = duckdb.connect('data/baseball.duckdb', read_only=True)

june_pitchers = con.execute("""
    SELECT DISTINCT pitcher
    FROM pa_events
    WHERE game_date >= '2026-06-01' AND game_date <= '2026-06-14'
    AND pitcher IN (
        SELECT pitcher
        FROM pa_events
        WHERE game_date >= '2026-06-01' AND game_date <= '2026-06-14'
        GROUP BY game_pk, pitcher
        HAVING COUNT(*) >= 10
    )
""").fetchdf()

print("\n" + "=" * 80)
print("V2 PITCHER BASELINE COVERAGE")
print("=" * 80)

total_pitchers = len(june_pitchers)
covered = sum(1 for p in june_pitchers['pitcher'] if p in v2.pitcher_baselines)
uncovered = total_pitchers - covered

print(f"\nJune 1-14 starting pitchers: {total_pitchers}")
print(f"Covered by V2 baselines: {covered}")
print(f"Missing baselines: {uncovered}")
print(f"Coverage rate: {100*covered/total_pitchers:.1f}%")

print(f"\nTotal pitchers in V2 baseline database: {len(v2.pitcher_baselines)}")

# Show which pitchers are missing
if uncovered > 0:
    print(f"\n{uncovered} pitchers WITHOUT baselines:")
    for pitcher_id in june_pitchers['pitcher']:
        if pitcher_id not in v2.pitcher_baselines:
            # Try to get name
            name_result = con.execute(f"""
                SELECT name FROM pitchers WHERE player_id = {pitcher_id} AND season = 2026
            """).fetchdf()

            name = name_result['name'].iloc[0] if len(name_result) > 0 else "Unknown"

            # Get their June stats
            june_stats = con.execute(f"""
                SELECT
                    COUNT(*) as pa,
                    SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as k_rate
                FROM pa_events
                WHERE pitcher = {pitcher_id}
                AND game_date >= '2026-06-01' AND game_date <= '2026-06-14'
            """).fetchone()

            print(f"  {pitcher_id} ({name}): {june_stats[0]} PA in June, {june_stats[1]:.1%} K-rate")

con.close()

print("\n" + "=" * 80)
print("EXPLANATION")
print("=" * 80)
print("""
V2 requires pitchers to have 50+ PAs in 2026 data to build a baseline.
If coverage is <100%, it means:
- Pitchers debuted after database cutoff (June 14)
- Rookies/call-ups with <50 PAs
- Pitchers not in 2026 season data

For uncovered pitchers, V2 falls back to global average (22.8% K-rate).
""")
