"""
Compare archetype K-rates vs actual pitcher K-rates - check signal loss
"""
import pandas as pd
import numpy as np

print("=" * 80)
print("ARCHETYPE vs PITCHER K-RATE SIGNAL LOSS")
print("=" * 80)

# Load data
pitcher_archetypes = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/pitcher_archetypes.csv')
interaction_matrix = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/exports/archetype_interaction_matrix.csv')

# Get archetype K-rates (average across all batter types)
archetype_k_rates = interaction_matrix.groupby('pitcher_archetype').agg({
    'total_pa': 'sum',
    'k_count': 'sum'
}).reset_index()
archetype_k_rates['k_rate'] = archetype_k_rates['k_count'] / archetype_k_rates['total_pa']
archetype_k_rates.rename(columns={'k_rate': 'k_rate_archetype'}, inplace=True)

# Load 2026 pitcher stats
gamelogs = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/data/pitcher_gamelogs_2024_2026.csv')
pitcher_stats_2026 = gamelogs[gamelogs['season'] == 2026].groupby('pitcher_id').agg({
    'K': 'sum',
    'BF': 'sum',
    'pitcher': 'first'
}).reset_index()
pitcher_stats_2026['k_rate_2026'] = pitcher_stats_2026['K'] / pitcher_stats_2026['BF']
pitcher_stats_2026.rename(columns={'pitcher': 'pitcher_name'}, inplace=True)

backtest = pd.read_csv('C:/Users/carin/OneDrive/Dokument/stike/mlb-edge/analytics/backtest_june_archetype_full.csv')

# Merge pitcher archetype with 2026 stats
merged = pitcher_archetypes.merge(pitcher_stats_2026, left_on='player_id', right_on='pitcher_id', how='inner')
merged = merged.merge(archetype_k_rates[['pitcher_archetype', 'k_rate_archetype']],
                     left_on='archetype', right_on='pitcher_archetype', how='left')

print(f"\nMatched {len(merged)} pitchers")

# Calculate signal loss
merged['k_rate_diff'] = merged['k_rate_2026'] - merged['k_rate_archetype']
merged['k_rate_abs_diff'] = merged['k_rate_diff'].abs()

print("\n1. OVERALL SIGNAL LOSS:")
print("-" * 80)
print(f"Mean absolute K% difference: {merged['k_rate_abs_diff'].mean():.4f} ({merged['k_rate_abs_diff'].mean()*100:.2f}%)")
print(f"Median absolute K% difference: {merged['k_rate_abs_diff'].median():.4f}")
print(f"Max absolute K% difference: {merged['k_rate_abs_diff'].max():.4f}")

# Correlation between archetype and actual
corr = merged['k_rate_archetype'].corr(merged['k_rate_2026'])
print(f"\nCorrelation (archetype K% vs 2026 K%): {corr:.3f}")

# Show by archetype
print("\n2. SIGNAL LOSS BY ARCHETYPE:")
print("-" * 80)

for arch_id in sorted(merged['archetype'].unique()):
    arch_data = merged[merged['archetype'] == arch_id]

    print(f"\nArchetype {arch_id} (n={len(arch_data)}):")
    print(f"  Archetype mean K%: {arch_data['k_rate_archetype'].mean():.4f}")
    print(f"  2026 mean K%:      {arch_data['k_rate_2026'].mean():.4f}")
    print(f"  Mean abs diff:     {arch_data['k_rate_abs_diff'].mean():.4f}")
    print(f"  Range (2026 K%):   [{arch_data['k_rate_2026'].min():.3f}, {arch_data['k_rate_2026'].max():.3f}]")

# Focus on June 1-14 backtest pitchers
print("\n3. JUNE 1-14 BACKTEST PITCHERS:")
print("-" * 80)

# Get unique pitchers from backtest
backtest_arch = backtest[backtest['method'] == 'archetype']
backtest_pitchers = backtest_arch[['pitcher_id', 'pitcher_name']].drop_duplicates()
backtest_merged = backtest_pitchers.merge(merged, on='pitcher_id', how='left')

print(f"\nBacktest pitchers using archetype: {len(backtest_merged)}")
print(f"With archetype data: {backtest_merged['archetype'].notna().sum()}")

backtest_merged_clean = backtest_merged.dropna(subset=['archetype', 'k_rate_archetype', 'k_rate_2026'])

if len(backtest_merged_clean) > 0:
    print(f"\nBacktest signal loss:")
    print(f"  Mean abs K% diff: {backtest_merged_clean['k_rate_abs_diff'].mean():.4f}")
    print(f"  Correlation:      {backtest_merged_clean['k_rate_archetype'].corr(backtest_merged_clean['k_rate_2026']):.3f}")

    # Show worst cases
    print("\nWorst 15 cases (archetype vs reality):")
    worst = backtest_merged_clean.nlargest(15, 'k_rate_abs_diff')[
        ['pitcher_name_y', 'archetype', 'k_rate_archetype', 'k_rate_2026', 'k_rate_diff']
    ]
    worst.rename(columns={'pitcher_name_y': 'pitcher_name'}, inplace=True)
    print(worst.to_string(index=False))
else:
    print("\nNo data to analyze!")

# Check the specific bad predictions mentioned
print("\n4. SPECIFIC BAD PREDICTIONS:")
print("-" * 80)

bad_prediction_pitchers = ['Jacob Misiorowski', 'Jesus Luzardo']
for pitcher_name in bad_prediction_pitchers:
    pitcher_data = backtest_merged_clean[backtest_merged_clean['pitcher_name_y'].str.contains(pitcher_name, case=False, na=False)]

    if len(pitcher_data) > 0:
        row = pitcher_data.iloc[0]
        print(f"\n{row['pitcher_name_y']}:")
        print(f"  Archetype: {int(row['archetype'])}")
        print(f"  Archetype K%: {row['k_rate_archetype']:.4f} ({row['k_rate_archetype']*100:.1f}%)")
        print(f"  2026 K%:      {row['k_rate_2026']:.4f} ({row['k_rate_2026']*100:.1f}%)")
        print(f"  Difference:   {row['k_rate_diff']:+.4f} ({row['k_rate_diff']*100:+.1f}%)")

        # Get their backtest results
        pitcher_backtest = backtest[backtest['pitcher_name'].str.contains(pitcher_name, case=False, na=False)]
        if len(pitcher_backtest) > 0:
            print(f"  Backtest appearances: {len(pitcher_backtest)}")
            print(f"  Mean predicted K: {pitcher_backtest['predicted_ks'].mean():.1f}")
            print(f"  Mean actual K:    {pitcher_backtest['actual_ks'].mean():.1f}")
            print(f"  Mean error:       {pitcher_backtest['error'].mean():+.1f}")
    else:
        print(f"\n{pitcher_name}: NOT FOUND in backtest data")

print("\n" + "=" * 80)
