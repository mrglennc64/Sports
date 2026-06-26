"""
Retrospective validation of archetype model on June 25, 2026 actual results

Generates predictions using current archetype model API for pitchers who ACTUALLY started
on June 25, then compares to actual strikeout totals.
"""

import asyncio
import sys
sys.path.append('backend')

from app.data.client import StatsApiClient
from app.models.archetype_predictor import ArchetypePredictor
import duckdb
import pandas as pd

# June 25 actual starters and results (from MLB Stats API)
JUNE_25_ACTUALS = [
    {'pitcher': 'Bryce Miller', 'player_id': 682243, 'team': 'Seattle Mariners', 'actual_k': 11, 'bf': 22},
    {'pitcher': 'Tatsuya Imai', 'player_id': 683616, 'team': 'Houston Astros', 'actual_k': 10, 'bf': 21},
    {'pitcher': 'Connelly Early', 'player_id': 694311, 'team': 'Boston Red Sox', 'actual_k': 9, 'bf': 24},
    {'pitcher': 'Cam Schlittler', 'player_id': 694311, 'team': 'New York Yankees', 'actual_k': 9, 'bf': 25},
    {'pitcher': 'Ian Seymour', 'player_id': 686567, 'team': 'Tampa Bay Rays', 'actual_k': 7, 'bf': 21},
    {'pitcher': 'Cade Cavalli', 'player_id': 676825, 'team': 'Washington Nationals', 'actual_k': 7, 'bf': 25},
    {'pitcher': 'Landen Roupp', 'player_id': 695444, 'team': 'San Francisco Giants', 'actual_k': 6, 'bf': 24},
    {'pitcher': 'Jeffrey Springs', 'player_id': 671014, 'team': 'Athletics', 'actual_k': 6, 'bf': 21},
    {'pitcher': 'Troy Melton', 'player_id': 681220, 'team': 'Detroit Tigers', 'actual_k': 6, 'bf': 20},
    {'pitcher': 'Cristopher Sánchez', 'player_id': 677500, 'team': 'Philadelphia Phillies', 'actual_k': 6, 'bf': 25},
    {'pitcher': 'Freddy Peralta', 'player_id': 642547, 'team': 'New York Mets', 'actual_k': 5, 'bf': 24},
    {'pitcher': 'MacKenzie Gore', 'player_id': 669022, 'team': 'Texas Rangers', 'actual_k': 5, 'bf': 25},
    {'pitcher': 'Kevin Gausman', 'player_id': 592332, 'team': 'Toronto Blue Jays', 'actual_k': 4, 'bf': 28},
    {'pitcher': 'Bubba Chandler', 'player_id': 695448, 'team': 'Pittsburgh Pirates', 'actual_k': 4, 'bf': 23},
    {'pitcher': 'Matthew Boyd', 'player_id': 571510, 'team': 'Chicago Cubs', 'actual_k': 4, 'bf': 21},
    {'pitcher': 'Seth Lugo', 'player_id': 607625, 'team': 'Kansas City Royals', 'actual_k': 3, 'bf': 24},
]

async def main():
    print("=" * 100)
    print("ARCHETYPE MODEL VALIDATION - JUNE 25, 2026 ACTUAL STARTERS")
    print("=" * 100)

    predictor = ArchetypePredictor()

    # Generate predictions using archetype model
    predictions = []
    for p in JUNE_25_ACTUALS:
        # Use average opponent batter (real app would use actual lineup)
        # Using Mike Trout's ID as a placeholder for "average MLB batter"
        pred = predictor.predict(p['player_id'], 545361)

        predicted_k = pred['k_rate'] * p['bf']

        predictions.append({
            'pitcher': p['pitcher'],
            'team': p['team'],
            'predicted_k': predicted_k,
            'actual_k': p['actual_k'],
            'batters_faced': p['bf'],
            'error': predicted_k - p['actual_k'],
            'method': pred['method']
        })

    df = pd.DataFrame(predictions)
    df['abs_error'] = df['error'].abs()

    print(f"\n{len(df)} pitchers validated\n")
    print(df[['pitcher', 'predicted_k', 'actual_k', 'error', 'batters_faced', 'method']].to_string(index=False))

    # Metrics
    mae = df['abs_error'].mean()
    rmse = (df['error'] ** 2).mean() ** 0.5
    correlation = df['predicted_k'].corr(df['actual_k'])

    # Over/Under accuracy
    df['prediction_direction'] = df['predicted_k'].apply(lambda x: 'OVER' if x > 5.5 else 'UNDER')
    df['actual_direction'] = df['actual_k'].apply(lambda x: 'OVER' if x > 5.5 else 'UNDER')
    df['direction_correct'] = df['prediction_direction'] == df['actual_direction']

    direction_accuracy = df['direction_correct'].mean() * 100

    print(f"\n{'='*100}")
    print("PERFORMANCE METRICS")
    print(f"{'='*100}")
    print(f"Mean Absolute Error (MAE): {mae:.2f} strikeouts")
    print(f"Root Mean Squared Error (RMSE): {rmse:.2f} strikeouts")
    print(f"Correlation: {correlation:.3f}")
    print(f"OVER/UNDER Accuracy (5.5 line): {direction_accuracy:.1f}%")

    # Prediction method breakdown
    print(f"\n{'='*100}")
    print("PREDICTION METHOD BREAKDOWN")
    print(f"{'='*100}")
    method_counts = df['method'].value_counts()
    print(method_counts)

    # Best/worst
    print(f"\n{'='*100}")
    print("BEST PREDICTIONS (smallest error)")
    print(f"{'='*100}")
    best = df.nsmallest(5, 'abs_error')[['pitcher', 'predicted_k', 'actual_k', 'error']]
    for _, row in best.iterrows():
        print(f"{row['pitcher']:25s}: Predicted {row['predicted_k']:.1f}, Actual {row['actual_k']} (error: {row['error']:+.1f})")

    print(f"\n{'='*100}")
    print("WORST PREDICTIONS (largest error)")
    print(f"{'='*100}")
    worst = df.nlargest(5, 'abs_error')[['pitcher', 'predicted_k', 'actual_k', 'error']]
    for _, row in worst.iterrows():
        print(f"{row['pitcher']:25s}: Predicted {row['predicted_k']:.1f}, Actual {row['actual_k']} (error: {row['error']:+.1f})")

    # Save
    df.to_csv('analytics/june25_archetype_validation.csv', index=False)
    print(f"\nSaved to analytics/june25_archetype_validation.csv")

if __name__ == '__main__':
    asyncio.run(main())
