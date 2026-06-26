"""
Export all pitcher archetype groups with complete stats to CSV

Creates a comprehensive view of all 6 pitcher archetypes showing:
- Which pitchers are in each group
- Their 2026 stats (K%, BB%, velocity, etc.)
- Group averages
"""

import pandas as pd
import duckdb

print("=" * 100)
print("EXPORTING PITCHER ARCHETYPE GROUPS")
print("=" * 100)

# Load archetype assignments
print("\n[1] Loading archetype assignments...")
pitcher_archetypes = pd.read_csv('data/exports/pitcher_archetypes.csv')
print(f"Loaded {len(pitcher_archetypes)} pitcher archetype assignments")

# Load interaction matrix to get archetype labels
interaction_matrix = pd.read_csv('data/exports/archetype_interaction_matrix.csv')
archetype_labels = interaction_matrix[['pitcher_archetype', 'pitcher_label']].drop_duplicates()

# Connect to database to get pitcher stats
print("\n[2] Loading pitcher stats from database...")
con = duckdb.connect('data/baseball.duckdb', read_only=True)

# Get 2026 stats
pitcher_stats_2026 = con.execute("""
    SELECT
        pitcher,
        COUNT(*) as pa_2026,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as k_rate_2026,
        SUM(CASE WHEN events = 'walk' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as bb_rate_2026,
        SUM(CASE WHEN events IN ('single','double','triple','home_run') THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as hit_rate_2026
    FROM pa_events
    WHERE season = 2026
    GROUP BY pitcher
""").fetchdf()

# Get pitcher names
pitcher_names = con.execute("""
    SELECT player_id, name
    FROM pitchers
    WHERE season = 2026
""").fetchdf()

# Get all-time career stats for context
pitcher_stats_career = con.execute("""
    SELECT
        pitcher,
        COUNT(*) as pa_career,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as k_rate_career,
        SUM(CASE WHEN events = 'walk' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as bb_rate_career
    FROM pa_events
    GROUP BY pitcher
""").fetchdf()

con.close()

# Merge everything together
print("\n[3] Merging data...")
pitchers_full = pitcher_archetypes.merge(
    pitcher_names,
    left_on='player_id',
    right_on='player_id',
    how='left'
).merge(
    pitcher_stats_2026,
    left_on='player_id',
    right_on='pitcher',
    how='left'
).merge(
    pitcher_stats_career,
    left_on='player_id',
    right_on='pitcher',
    how='left'
).merge(
    archetype_labels,
    left_on='archetype',
    right_on='pitcher_archetype',
    how='left'
)

# Clean up
pitchers_full = pitchers_full[[
    'archetype',
    'pitcher_label',
    'player_id',
    'name',
    'pa_2026',
    'k_rate_2026',
    'bb_rate_2026',
    'hit_rate_2026',
    'pa_career',
    'k_rate_career',
    'bb_rate_career'
]]

# Convert rates to percentages
for col in ['k_rate_2026', 'bb_rate_2026', 'hit_rate_2026', 'k_rate_career', 'bb_rate_career']:
    pitchers_full[col] = (pitchers_full[col] * 100).round(1)

# Fill NaN for pitchers without 2026 data
pitchers_full = pitchers_full.fillna({
    'pa_2026': 0,
    'k_rate_2026': 0,
    'bb_rate_2026': 0,
    'hit_rate_2026': 0
})

# Sort by archetype, then by K-rate
pitchers_full = pitchers_full.sort_values(['archetype', 'k_rate_2026'], ascending=[True, False])

# Save main export
output_path = 'analytics/pitcher_archetype_groups_full.csv'
pitchers_full.to_csv(output_path, index=False)
print(f"\nSaved full data to {output_path}")

# Create summary by archetype
print("\n[4] Creating archetype summaries...")
summary = pitchers_full.groupby(['archetype', 'pitcher_label']).agg({
    'player_id': 'count',
    'pa_2026': 'sum',
    'k_rate_2026': 'mean',
    'bb_rate_2026': 'mean',
    'hit_rate_2026': 'mean',
    'k_rate_career': 'mean',
    'bb_rate_career': 'mean'
}).round(1)

summary.columns = [
    'num_pitchers',
    'total_pa_2026',
    'avg_k_pct_2026',
    'avg_bb_pct_2026',
    'avg_hit_pct_2026',
    'avg_k_pct_career',
    'avg_bb_pct_career'
]

summary = summary.reset_index()

summary_path = 'analytics/pitcher_archetype_summary.csv'
summary.to_csv(summary_path, index=False)
print(f"Saved summary to {summary_path}")

# Print summary to console
print("\n" + "=" * 100)
print("PITCHER ARCHETYPE SUMMARY")
print("=" * 100)
print(summary.to_string(index=False))

# Show top pitchers from each archetype
print("\n" + "=" * 100)
print("TOP 5 PITCHERS FROM EACH ARCHETYPE (by 2026 K%)")
print("=" * 100)

for arch in sorted(pitchers_full['archetype'].unique()):
    arch_pitchers = pitchers_full[pitchers_full['archetype'] == arch]
    label = arch_pitchers['pitcher_label'].iloc[0] if len(arch_pitchers) > 0 else "Unknown"

    print(f"\nArchetype {arch}: {label} ({len(arch_pitchers)} pitchers)")
    top5 = arch_pitchers.nlargest(5, 'k_rate_2026')[['name', 'k_rate_2026', 'bb_rate_2026', 'pa_2026']]
    if len(top5) > 0:
        print(top5.to_string(index=False))
    else:
        print("  No pitchers with 2026 data")

print("\n" + "=" * 100)
print("FILES CREATED:")
print("=" * 100)
print(f"1. {output_path} - All pitchers with full stats")
print(f"2. {summary_path} - Summary by archetype")
