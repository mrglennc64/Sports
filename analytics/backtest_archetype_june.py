"""
Backtest archetype model on June 1-14, 2026

Tests archetype predictions vs actual strikeout results across all June games
in the database. Compares archetype model performance to baseline.
"""

import sys
sys.path.append('backend')

import duckdb
import pandas as pd
from app.models.archetype_predictor import ArchetypePredictor
import numpy as np

print("=" * 100)
print("ARCHETYPE MODEL BACKTEST: JUNE 1-14, 2026")
print("=" * 100)

# Connect to database
con = duckdb.connect('data/baseball.duckdb', read_only=True)

# Get all June games with starting pitchers (10+ batters faced)
print("\n[1] Loading June 1-14 data...")

query = """
SELECT
    game_date,
    game_pk,
    pitcher,
    COUNT(*) as total_batters,
    SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as actual_ks
FROM pa_events
WHERE game_date >= '2026-06-01'
  AND game_date <= '2026-06-14'
GROUP BY game_date, game_pk, pitcher
HAVING total_batters >= 10
ORDER BY game_date, game_pk
"""

games_df = con.execute(query).fetchdf()

print(f"Found {len(games_df)} starting pitcher performances")
print(f"Date range: {games_df['game_date'].min()} to {games_df['game_date'].max()}")
print(f"Total games: {games_df['game_pk'].nunique()}")

# Get pitcher names
pitcher_names = con.execute("""
    SELECT player_id, name
    FROM pitchers
    WHERE season = 2026
""").fetchdf()

games_df = games_df.merge(
    pitcher_names,
    left_on='pitcher',
    right_on='player_id',
    how='left'
)

# Initialize archetype predictor
print("\n[2] Loading archetype model...")
predictor = ArchetypePredictor()

# Generate predictions
print("\n[3] Generating predictions...")

predictions = []
for idx, row in games_df.iterrows():
    # Use average opponent (placeholder - real model would use actual lineups)
    pred = predictor.predict(row['pitcher'], 545361)

    # Convert K rate to expected Ks
    expected_ks = pred['k_rate'] * row['total_batters']

    predictions.append({
        'game_date': row['game_date'],
        'game_pk': row['game_pk'],
        'pitcher_id': row['pitcher'],
        'pitcher_name': row['name'] if pd.notna(row['name']) else 'Unknown',
        'batters_faced': row['total_batters'],
        'actual_ks': row['actual_ks'],
        'predicted_ks': expected_ks,
        'k_rate': pred['k_rate'],
        'method': pred['method'],
        'error': expected_ks - row['actual_ks']
    })

pred_df = pd.DataFrame(predictions)
pred_df['abs_error'] = pred_df['error'].abs()

# Overall metrics
print("\n" + "=" * 100)
print("OVERALL PERFORMANCE METRICS")
print("=" * 100)

mae = pred_df['abs_error'].mean()
rmse = np.sqrt((pred_df['error'] ** 2).mean())
correlation = pred_df['predicted_ks'].corr(pred_df['actual_ks'])
coverage = len(pred_df[pred_df['method'] == 'archetype']) / len(pred_df) * 100

print(f"\nTotal pitcher performances: {len(pred_df)}")
print(f"Mean Absolute Error (MAE): {mae:.2f} strikeouts")
print(f"Root Mean Squared Error (RMSE): {rmse:.2f} strikeouts")
print(f"Correlation: {correlation:.3f}")
print(f"Archetype coverage: {coverage:.1f}%")

# Breakdown by prediction method
print("\n" + "=" * 100)
print("BREAKDOWN BY PREDICTION METHOD")
print("=" * 100)

method_stats = pred_df.groupby('method').agg({
    'abs_error': ['count', 'mean'],
    'error': lambda x: np.sqrt((x ** 2).mean()),
    'predicted_ks': lambda x: x.corr(pred_df.loc[x.index, 'actual_ks'])
}).round(3)

method_stats.columns = ['count', 'mae', 'rmse', 'correlation']
print(method_stats)

# Day-by-day performance
print("\n" + "=" * 100)
print("DAY-BY-DAY PERFORMANCE")
print("=" * 100)

daily_stats = pred_df.groupby('game_date').agg({
    'abs_error': ['count', 'mean'],
    'predicted_ks': lambda x: x.corr(pred_df.loc[x.index, 'actual_ks'])
}).round(3)

daily_stats.columns = ['games', 'mae', 'correlation']
print(daily_stats)

# OVER/UNDER betting simulation (5.5 line)
print("\n" + "=" * 100)
print("BETTING SIMULATION (5.5 K LINE)")
print("=" * 100)

pred_df['predicted_over'] = pred_df['predicted_ks'] > 5.5
pred_df['actual_over'] = pred_df['actual_ks'] > 5.5
pred_df['correct'] = pred_df['predicted_over'] == pred_df['actual_over']

accuracy = pred_df['correct'].mean() * 100
total_bets = len(pred_df)
wins = pred_df['correct'].sum()
losses = total_bets - wins

print(f"Total bets: {total_bets}")
print(f"Wins: {wins}")
print(f"Losses: {losses}")
print(f"Accuracy: {accuracy:.1f}%")
print(f"ROI (assuming -110 odds): {((wins * 0.909 - losses) / total_bets * 100):.1f}%")

# Best predictions
print("\n" + "=" * 100)
print("TOP 10 BEST PREDICTIONS")
print("=" * 100)

best = pred_df.nsmallest(10, 'abs_error')[['game_date', 'pitcher_name', 'predicted_ks', 'actual_ks', 'error', 'method']]
print(best.to_string(index=False))

# Worst predictions
print("\n" + "=" * 100)
print("TOP 10 WORST PREDICTIONS")
print("=" * 100)

worst = pred_df.nlargest(10, 'abs_error')[['game_date', 'pitcher_name', 'predicted_ks', 'actual_ks', 'error', 'method']]
print(worst.to_string(index=False))

# Save full results
output_path = 'analytics/backtest_june_archetype_full.csv'
pred_df.to_csv(output_path, index=False)
print(f"\n\nSaved full results to {output_path}")

# Summary by archetype vs fallback
print("\n" + "=" * 100)
print("ARCHETYPE vs FALLBACK COMPARISON")
print("=" * 100)

archetype_df = pred_df[pred_df['method'] == 'archetype']
fallback_df = pred_df[pred_df['method'] != 'archetype']

print(f"\nARCHETYPE MODEL ({len(archetype_df)} predictions):")
print(f"  MAE: {archetype_df['abs_error'].mean():.2f}")
print(f"  RMSE: {np.sqrt((archetype_df['error'] ** 2).mean()):.2f}")
print(f"  Correlation: {archetype_df['predicted_ks'].corr(archetype_df['actual_ks']):.3f}")
print(f"  Betting accuracy: {(archetype_df['correct'].mean() * 100):.1f}%")

print(f"\nFALLBACK ({len(fallback_df)} predictions):")
print(f"  MAE: {fallback_df['abs_error'].mean():.2f}")
print(f"  RMSE: {np.sqrt((fallback_df['error'] ** 2).mean()):.2f}")
print(f"  Correlation: {fallback_df['predicted_ks'].corr(fallback_df['actual_ks']):.3f}")
print(f"  Betting accuracy: {(fallback_df['correct'].mean() * 100):.1f}%")

improvement = ((fallback_df['abs_error'].mean() - archetype_df['abs_error'].mean()) /
               fallback_df['abs_error'].mean() * 100)
print(f"\nArchetype improvement vs fallback: {improvement:+.1f}%")

con.close()

print("\n" + "=" * 100)
print("BACKTEST COMPLETE")
print("=" * 100)
