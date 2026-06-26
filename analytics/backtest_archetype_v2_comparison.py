"""
Compare Archetype V1 vs V2 vs Baseline on June 1-14 backtest

Tests three prediction methods:
- V1 (old): Archetype cluster averages (loses pitcher skill)
- V2 (fixed): Pitcher baseline + batter archetype adjustment
- Baseline: Simple pitcher K-rate (no archetype)

Expected result: V2 should beat V1 by preserving pitcher skill while
adding batter matchup context.
"""

import sys
sys.path.append('backend')

import duckdb
import pandas as pd
import numpy as np
from app.models.archetype_predictor import ArchetypePredictor
from app.models.archetype_predictor_v2 import ArchetypePredictorV2

print("=" * 100)
print("ARCHETYPE V1 vs V2 vs BASELINE COMPARISON - JUNE 1-14, 2026")
print("=" * 100)

# Load June backtest data
con = duckdb.connect('data/baseball.duckdb', read_only=True)

games_df = con.execute("""
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
""").fetchdf()

print(f"\n[1] Loaded {len(games_df)} pitcher performances")

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

# Initialize predictors
print("\n[2] Loading models...")
v1_predictor = ArchetypePredictor()
v2_predictor = ArchetypePredictorV2()

# Get baseline K-rates from database
pitcher_baselines = con.execute("""
    SELECT
        pitcher,
        COUNT(*) as total_pa,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as k_rate
    FROM pa_events
    WHERE season = 2026
    GROUP BY pitcher
    HAVING COUNT(*) >= 50
""").fetchdf()

baseline_map = dict(zip(pitcher_baselines['pitcher'], pitcher_baselines['k_rate']))
global_baseline = 0.228  # MLB average

con.close()

# Generate predictions with all three methods
print("\n[3] Generating predictions...")

results = []
for _, row in games_df.iterrows():
    pitcher_id = row['pitcher']
    batter_id = 660271  # Example batter

    # V1 prediction
    v1_pred = v1_predictor.predict(pitcher_id, batter_id)
    v1_k_rate = v1_pred['k_rate']
    v1_expected = v1_k_rate * row['total_batters']

    # V2 prediction
    v2_pred = v2_predictor.predict(pitcher_id, batter_id)
    v2_k_rate = v2_pred['k_rate']
    v2_expected = v2_k_rate * row['total_batters']

    # Baseline prediction (just pitcher K-rate, no archetype)
    baseline_k_rate = baseline_map.get(pitcher_id, global_baseline)
    baseline_expected = baseline_k_rate * row['total_batters']

    results.append({
        'game_date': row['game_date'],
        'pitcher_id': pitcher_id,
        'pitcher_name': row['name'] if pd.notna(row['name']) else 'Unknown',
        'batters_faced': row['total_batters'],
        'actual_ks': row['actual_ks'],

        # V1 (old archetype)
        'v1_predicted': v1_expected,
        'v1_error': v1_expected - row['actual_ks'],
        'v1_method': v1_pred['method'],

        # V2 (fixed archetype)
        'v2_predicted': v2_expected,
        'v2_error': v2_expected - row['actual_ks'],
        'v2_method': v2_pred['method'],

        # Baseline (simple pitcher K-rate)
        'baseline_predicted': baseline_expected,
        'baseline_error': baseline_expected - row['actual_ks'],
    })

df = pd.DataFrame(results)
df['v1_abs_error'] = df['v1_error'].abs()
df['v2_abs_error'] = df['v2_error'].abs()
df['baseline_abs_error'] = df['baseline_error'].abs()

# Overall comparison
print("\n" + "=" * 100)
print("OVERALL PERFORMANCE COMPARISON")
print("=" * 100)

comparison = pd.DataFrame({
    'Model': ['V1 (Old Archetype)', 'V2 (Fixed Archetype)', 'Baseline (No Archetype)'],
    'MAE': [
        df['v1_abs_error'].mean(),
        df['v2_abs_error'].mean(),
        df['baseline_abs_error'].mean()
    ],
    'RMSE': [
        np.sqrt((df['v1_error'] ** 2).mean()),
        np.sqrt((df['v2_error'] ** 2).mean()),
        np.sqrt((df['baseline_error'] ** 2).mean())
    ],
    'Correlation': [
        df['v1_predicted'].corr(df['actual_ks']),
        df['v2_predicted'].corr(df['actual_ks']),
        df['baseline_predicted'].corr(df['actual_ks'])
    ]
})

print(comparison.to_string(index=False))

# Calculate improvements
v2_improvement_vs_v1 = (df['v1_abs_error'].mean() - df['v2_abs_error'].mean()) / df['v1_abs_error'].mean() * 100
v2_improvement_vs_baseline = (df['baseline_abs_error'].mean() - df['v2_abs_error'].mean()) / df['baseline_abs_error'].mean() * 100

print(f"\nV2 improvement vs V1: {v2_improvement_vs_v1:+.1f}%")
print(f"V2 improvement vs Baseline: {v2_improvement_vs_baseline:+.1f}%")

# Betting simulation (5.5 K line)
print("\n" + "=" * 100)
print("BETTING SIMULATION (5.5 K LINE)")
print("=" * 100)

for model in ['v1', 'v2', 'baseline']:
    pred_col = f'{model}_predicted'
    df[f'{model}_bet_correct'] = ((df[pred_col] > 5.5) == (df['actual_ks'] > 5.5))
    accuracy = df[f'{model}_bet_correct'].mean() * 100
    wins = df[f'{model}_bet_correct'].sum()
    losses = len(df) - wins
    roi = ((wins * 0.909 - losses) / len(df)) * 100

    print(f"\n{model.upper()}: Accuracy {accuracy:.1f}%, ROI {roi:+.1f}%")

# Show biggest differences between V1 and V2
print("\n" + "=" * 100)
print("TOP 10 BIGGEST V2 IMPROVEMENTS (vs V1)")
print("=" * 100)

df['v2_improvement'] = df['v1_abs_error'] - df['v2_abs_error']
best_improvements = df.nlargest(10, 'v2_improvement')[
    ['pitcher_name', 'actual_ks', 'v1_predicted', 'v2_predicted', 'v1_abs_error', 'v2_abs_error', 'v2_improvement']
]

print(best_improvements.to_string(index=False))

# Show where V2 made things worse
print("\n" + "=" * 100)
print("TOP 10 WORST V2 CHANGES (vs V1)")
print("=" * 100)

worst_changes = df.nsmallest(10, 'v2_improvement')[
    ['pitcher_name', 'actual_ks', 'v1_predicted', 'v2_predicted', 'v1_abs_error', 'v2_abs_error', 'v2_improvement']
]

print(worst_changes.to_string(index=False))

# Save results
output_path = 'analytics/backtest_v1_v2_baseline_comparison.csv'
df.to_csv(output_path, index=False)
print(f"\n\nSaved full comparison to {output_path}")

print("\n" + "=" * 100)
print("CONCLUSION")
print("=" * 100)

if df['v2_abs_error'].mean() < df['v1_abs_error'].mean():
    print("✓ V2 (Fixed Archetype) BEATS V1 (Old Archetype)")
    print(f"  Improvement: {v2_improvement_vs_v1:.1f}%")
else:
    print("✗ V2 did NOT improve over V1")

if df['v2_abs_error'].mean() < df['baseline_abs_error'].mean():
    print("✓ V2 BEATS Baseline (archetype adjustment adds value)")
    print(f"  Improvement: {v2_improvement_vs_baseline:.1f}%")
else:
    print("✗ V2 does NOT beat baseline (archetype adjustment hurts)")

print("\nRecommendation:")
if df['v2_abs_error'].mean() < min(df['v1_abs_error'].mean(), df['baseline_abs_error'].mean()):
    print("  → Deploy V2 to production (set archetype_predictor_v2 in weights.py)")
elif df['baseline_abs_error'].mean() < min(df['v1_abs_error'].mean(), df['v2_abs_error'].mean()):
    print("  → Disable archetype model entirely (set archetype_weight = 0.0)")
else:
    print("  → Keep V1 but investigate further")
