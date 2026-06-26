"""
Audit interaction matrix sample sizes - check if cells have sufficient data
"""
import pandas as pd
import numpy as np

# Load interaction matrix
matrix = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/archetype_interaction_matrix.csv')
matrix.rename(columns={'total_pa': 'pa_count'}, inplace=True)

print("=" * 80)
print("INTERACTION MATRIX SAMPLE SIZE AUDIT")
print("=" * 80)

# Show matrix structure
print(f"\nTotal cells in matrix: {len(matrix)}")
print(f"Pitcher archetypes: {matrix['pitcher_archetype'].nunique()}")
print(f"Batter archetypes: {matrix['batter_archetype'].nunique()}")

# Sample size distribution
print("\n1. SAMPLE SIZE DISTRIBUTION:")
print("-" * 80)

print(f"\nPA count statistics:")
print(f"  Mean:   {matrix['pa_count'].mean():.0f}")
print(f"  Median: {matrix['pa_count'].median():.0f}")
print(f"  Min:    {matrix['pa_count'].min():.0f}")
print(f"  Max:    {matrix['pa_count'].max():.0f}")
print(f"  Std:    {matrix['pa_count'].std():.0f}")

# Sample size categories
bins = [0, 100, 500, 1000, 2000, 5000, float('inf')]
labels = ['<100', '100-500', '500-1k', '1k-2k', '2k-5k', '5k+']
matrix['sample_category'] = pd.cut(matrix['pa_count'], bins=bins, labels=labels)

print("\nCell distribution by sample size:")
print(matrix['sample_category'].value_counts().sort_index())

# High variance cells
HIGH_VARIANCE_THRESHOLD = 1000
small_sample_cells = matrix[matrix['pa_count'] < HIGH_VARIANCE_THRESHOLD]

print(f"\n2. HIGH VARIANCE CELLS (< {HIGH_VARIANCE_THRESHOLD} PAs):")
print("-" * 80)
print(f"Count: {len(small_sample_cells)} / {len(matrix)} ({len(small_sample_cells)/len(matrix)*100:.1f}%)")
print(f"Total PAs in small cells: {small_sample_cells['pa_count'].sum():,}")
print(f"Total PAs overall: {matrix['pa_count'].sum():,}")

# Show worst cells
print("\nSmallest 20 cells:")
smallest = matrix.nsmallest(20, 'pa_count')[['pitcher_archetype', 'batter_archetype', 'pa_count', 'k_pct']]
print(smallest.to_string(index=False))

# Check if backtest predictions use small-sample cells
print("\n3. BACKTEST PREDICTION SAMPLE SIZE ANALYSIS:")
print("-" * 80)

# Load backtest predictions
backtest = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/analytics/backtest_june_archetype_full.csv')

# Filter to archetype method only
backtest = backtest[backtest['method'] == 'archetype']

# Need to reconstruct which matrix cells were used
# This requires pitcher archetypes
pitcher_archetypes = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/pitcher_archetypes.csv')

# Merge to get pitcher archetype for each backtest game
backtest = backtest.merge(pitcher_archetypes[['player_id', 'archetype']],
                         left_on='pitcher_id', right_on='player_id', how='left')
backtest.rename(columns={'archetype': 'pitcher_archetype'}, inplace=True)

print(f"\nBacktest games: {len(backtest)}")
print(f"Games with pitcher archetype: {backtest['pitcher_archetype'].notna().sum()}")

# Estimate sample size exposure
# For each pitcher archetype, show min/median/max PA counts available
print("\nPer-pitcher-archetype interaction sample sizes:")

for p_arch in sorted(backtest['pitcher_archetype'].dropna().unique()):
    arch_cells = matrix[matrix['pitcher_archetype'] == p_arch]

    print(f"\nPitcher Archetype {int(p_arch)}:")
    print(f"  Cells: {len(arch_cells)}")
    print(f"  Min PA:    {arch_cells['pa_count'].min():.0f}")
    print(f"  Median PA: {arch_cells['pa_count'].median():.0f}")
    print(f"  Max PA:    {arch_cells['pa_count'].max():.0f}")
    print(f"  Cells < 1000 PA: {(arch_cells['pa_count'] < 1000).sum()} / {len(arch_cells)}")

print("\n" + "=" * 80)
