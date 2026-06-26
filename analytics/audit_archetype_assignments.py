"""
Audit archetype assignments - check if pitchers are clustered correctly
"""
import pandas as pd
import numpy as np

# Load archetype assignments
archetypes = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/pitcher_archetypes.csv')

# Load 2026 pitcher stats for comparison
gamelogs = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/pitcher_gamelogs_2024_2026.csv')
pitcher_stats_2026 = gamelogs[gamelogs['season'] == 2026].groupby('pitcher_id').agg({
    'K': 'sum',
    'BF': 'sum',
    'BB': 'sum',
    'pitcher': 'first'
}).reset_index()
pitcher_stats_2026['k_rate'] = pitcher_stats_2026['K'] / pitcher_stats_2026['BF']
pitcher_stats_2026['bb_rate'] = pitcher_stats_2026['BB'] / pitcher_stats_2026['BF']
pitcher_stats_2026.rename(columns={'pitcher': 'pitcher_name'}, inplace=True)

print("=" * 80)
print("ARCHETYPE ASSIGNMENT AUDIT")
print("=" * 80)

# Show archetype distribution
print("\n1. ARCHETYPE DISTRIBUTION:")
print("-" * 80)
print(f"Total pitchers assigned: {len(archetypes)}")
print(f"Archetypes: {sorted(archetypes['archetype'].unique())}")
print("\nPitchers per archetype:")
print(archetypes['archetype'].value_counts().sort_index())

# Check if assignments match 2026 reality
print("\n2. ARCHETYPE vs 2026 K-RATES:")
print("-" * 80)

# Merge archetype assignments with 2026 stats
merged = archetypes.merge(pitcher_stats_2026, left_on='player_id', right_on='pitcher_id', how='inner')

print(f"\nMatched {len(merged)} pitchers with 2026 data")

# For each archetype, show 2026 K-rate range
for archetype_id in sorted(merged['archetype'].unique()):
    cluster_data = merged[merged['archetype'] == archetype_id]

    print(f"\nArchetype {archetype_id} (n={len(cluster_data)}):")
    print(f"  2026 K% mean:   {cluster_data['k_rate'].mean():.3f}")
    print(f"  2026 K% range:  [{cluster_data['k_rate'].min():.3f}, {cluster_data['k_rate'].max():.3f}]")
    print(f"  2026 K% std:    {cluster_data['k_rate'].std():.3f}")

# Get archetype labels from interaction matrix
matrix = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/archetype_interaction_matrix.csv')
arch_labels = matrix[['pitcher_archetype', 'pitcher_label']].drop_duplicates()

print("\n3. ARCHETYPE LABELS:")
print("-" * 80)
for _, row in arch_labels.sort_values('pitcher_archetype').iterrows():
    print(f"Archetype {row['pitcher_archetype']}: {row['pitcher_label']}")

# Check June 1-14 backtest pitchers specifically
print("\n4. JUNE 1-14 BACKTEST PITCHER ASSIGNMENTS:")
print("-" * 80)

# Load backtest results to get pitcher list
backtest = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/analytics/backtest_june_archetype_full.csv')

# Get unique pitchers who used archetype method
archetype_predictions = backtest[backtest['method'] == 'archetype']
print(f"\nBacktest games using archetype method: {len(archetype_predictions)}")
print(f"Unique pitchers: {archetype_predictions['pitcher_id'].nunique()}")

# Check if these pitchers have archetype assignments
backtest_pitchers = archetype_predictions.merge(archetypes, left_on='pitcher_id', right_on='player_id', how='left')

print(f"Pitchers with archetype: {backtest_pitchers['archetype'].notna().sum()}")
print(f"Missing archetype: {backtest_pitchers['archetype'].isna().sum()}")

if backtest_pitchers['archetype'].isna().any():
    print("\nWARNING: Some backtest pitchers using archetype method have no archetype assignment!")
    print(backtest_pitchers[backtest_pitchers['archetype'].isna()][['pitcher_name']].head(10))

print("\n" + "=" * 80)
