"""
Phase 6: Validate Archetype Model

Compares archetype-based predictions against actual outcomes on hold-out test set.

Run from mlb-edge/:
    python analytics/validate_archetype_model.py
"""

import sys
sys.path.append('backend')

import duckdb
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, log_loss, mean_squared_error
import matplotlib.pyplot as plt
from app.models.archetype_predictor import ArchetypePredictor

# Connect to database
con = duckdb.connect('data/baseball.duckdb', read_only=True)

print("=" * 100)
print("ARCHETYPE MODEL VALIDATION")
print("=" * 100)

# Hold-out test set: 2026 data (most recent)
print("\n[1] Loading test set (2026 data)...")

test_pa = con.execute("""
    SELECT
        pitcher,
        batter,
        CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END as is_k,
        CASE WHEN events IN ('walk', 'intent_walk') THEN 1 ELSE 0 END as is_bb,
        CASE WHEN events IN ('single', 'double', 'triple', 'home_run', 'walk', 'intent_walk', 'hit_by_pitch')
             THEN 1 ELSE 0 END as is_on_base
    FROM pa_events
    WHERE EXTRACT(YEAR FROM game_date) = 2026
      AND pitcher IS NOT NULL
      AND batter IS NOT NULL
""").fetchdf()

print(f"Test set size: {len(test_pa):,} PAs")
print(f"Actual K rate: {test_pa['is_k'].mean():.1%}")
print(f"Actual BB rate: {test_pa['is_bb'].mean():.1%}")

# Generate predictions
print("\n[2] Generating archetype predictions...")

predictor = ArchetypePredictor()

predictions = []
for idx, row in test_pa.iterrows():
    if idx % 10000 == 0:
        print(f"  Processed {idx:,}/{len(test_pa):,} PAs...")

    pred = predictor.predict(row['pitcher'], row['batter'])
    predictions.append({
        'pitcher': row['pitcher'],
        'batter': row['batter'],
        'pred_k_rate': pred['k_rate'],
        'pred_bb_rate': pred['bb_rate'],
        'actual_k': row['is_k'],
        'actual_bb': row['is_bb'],
        'method': pred['method']
    })

pred_df = pd.DataFrame(predictions)

print(f"\nPrediction method breakdown:")
print(pred_df['method'].value_counts())

# Filter to predictions that used archetype method (not fallbacks)
archetype_only = pred_df[pred_df['method'] == 'archetype']
print(f"\nArchetype predictions: {len(archetype_only):,} / {len(pred_df):,} ({100*len(archetype_only)/len(pred_df):.1f}%)")

# Metrics
print("\n[3] VALIDATION METRICS")
print("-" * 100)

def compute_metrics(df, name):
    """Compute validation metrics for K predictions."""
    print(f"\n{name}:")
    print(f"  Sample size: {len(df):,} PAs")

    # MAE (mean absolute error on binary outcome)
    mae = mean_absolute_error(df['actual_k'], df['pred_k_rate'])
    print(f"  MAE (K): {mae:.4f}")

    # RMSE
    rmse = np.sqrt(mean_squared_error(df['actual_k'], df['pred_k_rate']))
    print(f"  RMSE (K): {rmse:.4f}")

    # Log loss (probability calibration)
    # Clip predictions to avoid log(0)
    pred_clipped = df['pred_k_rate'].clip(0.01, 0.99)
    ll = log_loss(df['actual_k'], pred_clipped)
    print(f"  Log Loss (K): {ll:.4f}")

    # Brier score
    brier = np.mean((df['actual_k'] - df['pred_k_rate']) ** 2)
    print(f"  Brier Score (K): {brier:.4f}")

    # Calibration: bin predictions, compare to actual
    df['pred_bin'] = pd.cut(df['pred_k_rate'], bins=[0, 0.15, 0.20, 0.25, 0.30, 1.0],
                             labels=['<15%', '15-20%', '20-25%', '25-30%', '>30%'])
    calibration = df.groupby('pred_bin', observed=True).agg({
        'pred_k_rate': 'mean',
        'actual_k': 'mean',
        'pitcher': 'count'
    }).rename(columns={'pitcher': 'n'})

    print(f"\n  Calibration by predicted K bin:")
    print(calibration.to_string())

    return mae, rmse, ll, brier

# Compute for archetype-only predictions
mae_arch, rmse_arch, ll_arch, brier_arch = compute_metrics(archetype_only, "Archetype-based predictions")

# Compute for all predictions (including fallbacks)
mae_all, rmse_all, ll_all, brier_all = compute_metrics(pred_df, "All predictions (with fallbacks)")

# Baseline: predict global average
global_k_rate = test_pa['is_k'].mean()
baseline_mae = mean_absolute_error(test_pa['is_k'], [global_k_rate] * len(test_pa))
baseline_rmse = np.sqrt(mean_squared_error(test_pa['is_k'], [global_k_rate] * len(test_pa)))

print(f"\n\nBASELINE (predict global avg {global_k_rate:.1%} for all):")
print(f"  MAE: {baseline_mae:.4f}")
print(f"  RMSE: {baseline_rmse:.4f}")

print(f"\nIMPROVEMENT vs BASELINE:")
print(f"  MAE reduction: {100*(baseline_mae - mae_arch)/baseline_mae:.1f}%")
print(f"  RMSE reduction: {100*(baseline_rmse - rmse_arch)/baseline_rmse:.1f}%")

# Calibration plot
print("\n[4] Generating calibration plot...")

plt.figure(figsize=(10, 6))

# Perfect calibration line
plt.plot([0, 1], [0, 1], 'k--', alpha=0.3, label='Perfect calibration')

# Archetype predictions
bins = [0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 1.0]
archetype_only['pred_decile'] = pd.cut(archetype_only['pred_k_rate'], bins=bins)
calib_data = archetype_only.groupby('pred_decile', observed=True).agg({
    'pred_k_rate': 'mean',
    'actual_k': 'mean',
    'pitcher': 'count'
}).rename(columns={'pitcher': 'n'}).dropna()

plt.scatter(calib_data['pred_k_rate'], calib_data['actual_k'],
            s=calib_data['n']/50, alpha=0.6, label='Archetype model')

# Add sample sizes as annotations
for idx, row in calib_data.iterrows():
    plt.annotate(f"n={row['n']}",
                 (row['pred_k_rate'], row['actual_k']),
                 fontsize=8, alpha=0.7)

plt.xlabel('Predicted K Rate')
plt.ylabel('Actual K Rate')
plt.title('Archetype Model Calibration (2026 Test Set)')
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig('analytics/archetype_calibration_plot.png', dpi=150)
print("Saved to analytics/archetype_calibration_plot.png")

# Summary report
print("\n[5] SUMMARY")
print("=" * 100)

print(f"""
ARCHETYPE MODEL VALIDATION RESULTS:

Test Set: 2026 data ({len(test_pa):,} PAs)
Coverage: {100*len(archetype_only)/len(pred_df):.1f}% of PAs had archetype predictions

Performance (Archetype-only):
  MAE:         {mae_arch:.4f}
  RMSE:        {rmse_arch:.4f}
  Log Loss:    {ll_arch:.4f}
  Brier Score: {brier_arch:.4f}

vs Baseline (predict global avg):
  MAE improvement:  {100*(baseline_mae - mae_arch)/baseline_mae:+.1f}%
  RMSE improvement: {100*(baseline_rmse - rmse_arch)/baseline_rmse:+.1f}%

INTERPRETATION:
- MAE {mae_arch:.4f} means avg error of ~{mae_arch*100:.1f} percentage points per PA
- For 27 BF, expected error = {mae_arch*27:.2f} strikeouts
- {'GOOD' if mae_arch < 0.40 else 'NEEDS IMPROVEMENT'} calibration (MAE <0.40 is good for binary outcome)

NEXT STEPS:
1. Compare to existing type-based model (analytics/pure_prediction_test.py showed MAE=1.672 for game-level)
2. If archetype model is better, integrate into ensemble_pipeline.py
3. A/B test in production
""")

con.close()
