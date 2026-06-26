"""
Validate June 26, 2026 predictions against actual MLB results

Compares the predictions from the app screenshot to actual strikeout totals.
"""

import duckdb
import pandas as pd
from datetime import datetime

# Connect to database
con = duckdb.connect('data/baseball.duckdb', read_only=True)

print("=" * 100)
print("JUNE 26, 2026 PREDICTION VALIDATION")
print("=" * 100)

# Get actual results from June 26, 2026
actual_results = con.execute("""
    SELECT
        game_pk,
        game_date,
        pitcher,
        COUNT(*) as total_batters,
        SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as actual_ks
    FROM pa_events
    WHERE game_date = '2026-06-26'
    GROUP BY game_pk, game_date, pitcher
    HAVING actual_ks > 0  -- Only starters who got strikeouts
    ORDER BY actual_ks DESC
""").fetchdf()

print(f"\n[1] Found {len(actual_results)} pitchers with strikeouts on 2026-06-26")
print(actual_results.head(20).to_string(index=False))

# Get pitcher names
pitcher_names = con.execute("""
    SELECT DISTINCT player_id, name, season
    FROM pitchers
    WHERE season >= 2026
""").fetchdf()

# Merge to get names
actual_with_names = actual_results.merge(
    pitcher_names,
    left_on='pitcher',
    right_on='player_id',
    how='left'
)

print("\n[2] Actual strikeout totals with pitcher names:")
print(actual_with_names[['name', 'actual_ks', 'total_batters']].head(20).to_string(index=False))

# Predictions from screenshot 2 (Pro mode showing full slate)
predictions = {
    'Trevor Rogers': {'pred': 3.56, 'line': 4.5, 'side': 'UNDER'},
    'Andrew Alvarez': {'pred': 7.70, 'line': 4.5, 'side': 'OVER'},
    'Luis Castillo': {'pred': 6.22, 'line': 4.5, 'side': 'OVER'},
    'Will Warren': {'pred': 4.46, 'line': 4.5, 'side': 'UNDER'},
    'Nick Martinez': {'pred': 3.17, 'line': 3.5, 'side': 'UNDER'},
    'J.T. Ginn': {'pred': 6.04, 'line': 5.5, 'side': 'OVER'},
    'Taj Bradley': {'pred': 5.59, 'line': 6.5, 'side': 'UNDER'},
    'Zac Gallen': {'pred': 2.87, 'line': 3.5, 'side': 'UNDER'},
    'Nathan Eovaldi': {'pred': 5.71, 'line': 5.5, 'side': 'OVER'},
    'Roki Sasaki': {'pred': 6.02, 'line': 5.5, 'side': 'OVER'},
    'Spencer Arrighetti': {'pred': 6.26, 'line': 5.5, 'side': 'OVER'},
    'Tomoyuki Sugano': {'pred': 3.38, 'line': 3.5, 'side': 'UNDER'},
    'Colin Rea': {'pred': 4.21, 'line': 4.5, 'side': 'OVER'},
    'Andrew Abbott': {'pred': 5.27, 'line': 5.5, 'side': 'OVER'},
    'Max Meyer': {'pred': 5.60, 'line': 5.5, 'side': 'OVER'},
    'Michael McGreevy': {'pred': 3.54, 'line': 4.5, 'side': 'UNDER'},
    'Walker Buehler': {'pred': 4.54, 'line': 4.5, 'side': 'OVER'},
    'Paul Skenes': {'pred': 8.10, 'line': 8.5, 'side': 'OVER'},
    'Zack Wheeler': {'pred': 6.75, 'line': 6.5, 'side': 'UNDER'},
    'Payton Tolle': {'pred': 5.79, 'line': 5.5, 'side': 'OVER'},
    'Walbert Ureña': {'pred': 5.30, 'line': 4.5, 'side': 'OVER'},
    'Joey Cantillo': {'pred': 5.17, 'line': 5.5, 'side': 'UNDER'},
    'Jacob Misiorowski': {'pred': 8.36, 'line': 8.5, 'side': 'UNDER'},
    'Patrick Corbin': {'pred': 3.69, 'line': 4.5, 'side': 'UNDER'},
}

pred_df = pd.DataFrame([
    {'name': name, 'predicted_ks': data['pred'], 'line': data['line'], 'side': data['side']}
    for name, data in predictions.items()
])

print("\n[3] Predictions from screenshot:")
print(pred_df.head(20).to_string(index=False))

# Match predictions to actuals
comparison = pred_df.merge(
    actual_with_names[['name', 'actual_ks', 'total_batters']],
    on='name',
    how='left'
)

print("\n[4] PREDICTION vs ACTUAL COMPARISON:")
print("=" * 100)

comparison['error'] = comparison['predicted_ks'] - comparison['actual_ks']
comparison['abs_error'] = comparison['error'].abs()
comparison['correct_side'] = comparison.apply(
    lambda row: (
        (row['side'] == 'OVER' and row['actual_ks'] > row['line']) or
        (row['side'] == 'UNDER' and row['actual_ks'] < row['line'])
    ) if pd.notna(row['actual_ks']) else None,
    axis=1
)

# Sort by absolute error
comparison_sorted = comparison.sort_values('abs_error', ascending=True)

print(comparison_sorted.to_string(index=False))

# Summary statistics
matched = comparison.dropna(subset=['actual_ks'])
print(f"\n[5] SUMMARY STATISTICS")
print("=" * 100)
print(f"Pitchers matched: {len(matched)} / {len(predictions)}")
print(f"Coverage: {100*len(matched)/len(predictions):.1f}%")

if len(matched) > 0:
    mae = matched['abs_error'].mean()
    rmse = (matched['error'] ** 2).mean() ** 0.5
    correlation = matched['predicted_ks'].corr(matched['actual_ks'])

    print(f"\nPrediction Accuracy:")
    print(f"  MAE (Mean Absolute Error): {mae:.2f} strikeouts")
    print(f"  RMSE: {rmse:.2f} strikeouts")
    print(f"  Correlation: {correlation:.3f}")

    # Betting performance
    correct_sides = matched['correct_side'].sum()
    total_bets = len(matched)
    win_rate = 100 * correct_sides / total_bets if total_bets > 0 else 0

    print(f"\nBetting Performance:")
    print(f"  Correct sides: {correct_sides} / {total_bets}")
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  Expected (50/50): 50.0%")
    print(f"  Edge: {win_rate - 50:.1f} percentage points")

    # Over/Under breakdown
    overs = matched[matched['side'] == 'OVER']
    unders = matched[matched['side'] == 'UNDER']

    if len(overs) > 0:
        over_wins = overs['correct_side'].sum()
        print(f"\n  OVER bets: {over_wins}/{len(overs)} ({100*over_wins/len(overs):.1f}%)")

    if len(unders) > 0:
        under_wins = unders['correct_side'].sum()
        print(f"  UNDER bets: {under_wins}/{len(unders)} ({100*under_wins/len(unders):.1f}%)")

    # Best and worst predictions
    print(f"\nBest predictions (smallest error):")
    print(comparison_sorted[['name', 'predicted_ks', 'actual_ks', 'error', 'line', 'side', 'correct_side']].head(5).to_string(index=False))

    print(f"\nWorst predictions (largest error):")
    print(comparison_sorted[['name', 'predicted_ks', 'actual_ks', 'error', 'line', 'side', 'correct_side']].tail(5).to_string(index=False))

else:
    print("No matches found - data may not be available yet for 2026-06-26")

con.close()
