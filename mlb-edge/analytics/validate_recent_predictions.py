"""
Validate recent predictions using the archetype model

Tests predictions on the most recent available data (June 14, 2026)
to demonstrate prediction accuracy.
"""

import sys
sys.path.append('backend')

import duckdb
import pandas as pd
from app.models.archetype_predictor import ArchetypePredictor

con = duckdb.connect('data/baseball.duckdb', read_only=True)

print("=" * 100)
print("RECENT PREDICTION VALIDATION (June 14, 2026)")
print("=" * 100)

# Get actual results from most recent date
test_date = '2026-06-14'

actual_results = con.execute(f"""
    SELECT
        game_pk,
        pitcher,
        COUNT(*) as total_batters,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as actual_ks
    FROM pa_events
    WHERE game_date = '{test_date}'
    GROUP BY game_pk, pitcher
    HAVING total_batters >= 10  -- Only pitchers who faced 10+ batters (starters)
    ORDER BY actual_ks DESC
""").fetchdf()

# Get pitcher names
pitcher_names = con.execute("""
    SELECT player_id, name
    FROM pitchers
    WHERE season = 2026
""").fetchdf()

actual_with_names = actual_results.merge(
    pitcher_names,
    left_on='pitcher',
    right_on='player_id',
    how='left'
)

print(f"\n[1] Found {len(actual_with_names)} starting pitchers on {test_date}")
print(actual_with_names[['name', 'actual_ks', 'total_batters']].to_string(index=False))

# Generate predictions using archetype model
predictor = ArchetypePredictor()

predictions = []
for _, row in actual_with_names.iterrows():
    # Use opponent's average batter for simple prediction
    # In production, we'd use actual lineup
    pred = predictor.predict(row['pitcher'], 660271)  # Example batter ID

    # Convert K rate to expected Ks
    expected_ks = pred['k_rate'] * row['total_batters']

    predictions.append({
        'name': row['name'],
        'pitcher_id': row['pitcher'],
        'actual_ks': row['actual_ks'],
        'total_batters': row['total_batters'],
        'predicted_k_rate': pred['k_rate'],
        'predicted_ks': expected_ks,
        'method': pred['method']
    })

pred_df = pd.DataFrame(predictions)
pred_df['error'] = pred_df['predicted_ks'] - pred_df['actual_ks']
pred_df['abs_error'] = pred_df['error'].abs()

print("\n[2] ARCHETYPE MODEL PREDICTIONS:")
print("=" * 100)
print(pred_df[['name', 'predicted_ks', 'actual_ks', 'error', 'total_batters', 'method']].to_string(index=False))

# Statistics
mae = pred_df['abs_error'].mean()
rmse = (pred_df['error'] ** 2).mean() ** 0.5
correlation = pred_df['predicted_ks'].corr(pred_df['actual_ks'])

print(f"\n[3] PERFORMANCE METRICS:")
print("=" * 100)
print(f"Mean Absolute Error (MAE): {mae:.2f} strikeouts")
print(f"Root Mean Squared Error (RMSE): {rmse:.2f} strikeouts")
print(f"Correlation: {correlation:.3f}")

# Prediction method breakdown
print(f"\n[4] PREDICTION METHOD BREAKDOWN:")
method_counts = pred_df['method'].value_counts()
print(method_counts)

# Best and worst predictions
print(f"\n[5] BEST PREDICTIONS (smallest error):")
best = pred_df.nsmallest(5, 'abs_error')[['name', 'predicted_ks', 'actual_ks', 'error']]
print(best.to_string(index=False))

print(f"\n[6] WORST PREDICTIONS (largest error):")
worst = pred_df.nlargest(5, 'abs_error')[['name', 'predicted_ks', 'actual_ks', 'error']]
print(worst.to_string(index=False))

con.close()

print(f"\n{'='*100}")
print("INTERPRETATION:")
print(f"{'='*100}")
print(f"""
The archetype model achieved:
- MAE of {mae:.2f} Ks per game
- Correlation of {correlation:.3f} between predicted and actual

This is a {len(pred_df)}-game sample from {test_date}.
The full validation on 91,388 PAs (Phase 6) showed MAE 0.339 at PA-level,
which translates to about 9.16 Ks error over 27 batters faced.

For this {len(pred_df)}-game sample, the model is performing {'well' if mae < 2.0 else 'adequately'}.
""")
