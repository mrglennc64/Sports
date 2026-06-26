"""
A/B Test: Archetype Model vs Type-Based Model

Rigorous head-to-head comparison on identical 2026 test set.

Usage:
    cd mlb-edge/
    python analytics/ab_test_archetype_vs_type.py

Output:
    - Console: Comparison table with metrics
    - analytics/archetype_vs_type_comparison.txt: Full report
    - analytics/archetype_vs_type_calibration.png: Side-by-side calibration plots
"""

import sys
sys.path.append('backend')

from collections import defaultdict
import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, log_loss
from app.models.archetype_predictor import ArchetypePredictor


# ---- Configuration ----
DB = "data/baseball.duckdb"
TRAIN_YEARS = (2024, 2025)
TEST_YEAR = 2026
SHRINKAGE = 200.0  # Type-based model shrinkage parameter
MIN_BF = 12  # Minimum batters faced to count as a start


def load_test_pa_data(con):
    """Load 2026 PA-level test data."""
    print(f"\n[1] Loading {TEST_YEAR} test set from pa_events...")

    query = f"""
        SELECT
            game_pk,
            pitcher,
            batter,
            CASE WHEN events LIKE 'strikeout%' THEN 1 ELSE 0 END as is_k
        FROM pa_events
        WHERE season = {TEST_YEAR}
          AND pitcher IS NOT NULL
          AND batter IS NOT NULL
    """

    df = con.execute(query).fetchdf()
    print(f"  Loaded {len(df):,} PAs")
    print(f"  Actual K rate: {df['is_k'].mean():.1%}")

    return df


def build_type_model(con):
    """Build type-based model (pitcher cluster × batter cluster) from training data."""
    print(f"\n[2] Building type-based model from {TRAIN_YEARS}...")

    # Load training cell rates (same logic as pure_prediction_test.py)
    train_query = f"""
        SELECT pit.cluster_v2 AS p, bat.cluster_v2 AS b,
               count(*) n, count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events e
        JOIN pitchers pit ON pit.player_id = e.pitcher AND pit.season = e.season
        JOIN batters  bat ON bat.player_id = e.batter  AND bat.season = e.season
        WHERE e.season IN {TRAIN_YEARS}
        GROUP BY 1, 2
    """

    train_rows = con.execute(train_query).fetchall()

    cell_n, cell_k = {}, {}
    pmarg_n, pmarg_k = defaultdict(int), defaultdict(int)
    tot_n = tot_k = 0

    for p, b, n, k in train_rows:
        if p is None or b is None:
            continue
        cell_n[(p, b)] = n
        cell_k[(p, b)] = k
        pmarg_n[p] += n
        pmarg_k[p] += k
        tot_n += n
        tot_k += k

    league_rate = tot_k / tot_n
    pmarg_rate = {p: pmarg_k[p] / pmarg_n[p] for p in pmarg_n}

    print(f"  League rate: {league_rate:.1%}")
    print(f"  Pitcher clusters: {len(pmarg_rate)}")
    print(f"  Cells: {len(cell_n)}")

    def cell_k_rate(p, b):
        """Empirical Bayes shrinkage toward pitcher-type prior."""
        if p is None:
            return league_rate
        prior = pmarg_rate.get(p, league_rate)
        if b is None or (p, b) not in cell_n:
            return prior
        n, k = cell_n[(p, b)], cell_k[(p, b)]
        return (k + SHRINKAGE * prior) / (n + SHRINKAGE)

    return cell_k_rate, league_rate


def get_type_predictions(con, test_pa, cell_k_rate):
    """Generate PA-level predictions from type-based model."""
    print(f"\n[3] Generating type-based predictions...")

    # Load cluster mappings for 2026
    query = f"""
        SELECT
            e.game_pk,
            e.pitcher,
            e.batter,
            pit.cluster_v2 AS p_cluster,
            bat.cluster_v2 AS b_cluster
        FROM pa_events e
        LEFT JOIN pitchers pit ON pit.player_id = e.pitcher AND pit.season = {TEST_YEAR}
        LEFT JOIN batters  bat ON bat.player_id = e.batter  AND bat.season = {TEST_YEAR}
        WHERE e.season = {TEST_YEAR}
    """

    cluster_df = con.execute(query).fetchdf()

    # Merge with test_pa
    merged = test_pa.merge(cluster_df, on=['game_pk', 'pitcher', 'batter'], how='left')

    # Generate predictions
    predictions = []
    for _, row in merged.iterrows():
        pred_k_rate = cell_k_rate(row['p_cluster'], row['b_cluster'])
        predictions.append(pred_k_rate)

    merged['type_pred_k'] = predictions

    # Count coverage
    has_prediction = merged['type_pred_k'].notna()
    coverage = has_prediction.mean()

    print(f"  Coverage: {coverage:.1%}")

    return merged


def get_archetype_predictions(test_pa):
    """Generate PA-level predictions from archetype model."""
    print(f"\n[4] Generating archetype predictions...")

    predictor = ArchetypePredictor()

    predictions = []
    methods = []

    for idx, row in test_pa.iterrows():
        if idx % 10000 == 0 and idx > 0:
            print(f"  Processed {idx:,}/{len(test_pa):,} PAs...")

        pred = predictor.predict(row['pitcher'], row['batter'])
        predictions.append(pred['k_rate'])
        methods.append(pred['method'])

    test_pa['arch_pred_k'] = predictions
    test_pa['arch_method'] = methods

    # Count coverage (archetype method vs fallback)
    archetype_only = test_pa['arch_method'] == 'archetype'
    coverage = archetype_only.mean()

    print(f"  Coverage (archetype method): {coverage:.1%}")
    print(f"  Method breakdown:")
    print(test_pa['arch_method'].value_counts())

    return test_pa


def compute_metrics(y_true, y_pred, model_name):
    """Compute all validation metrics."""

    # Filter out NaN predictions
    valid_mask = ~np.isnan(y_pred)
    y_true_valid = y_true[valid_mask]
    y_pred_valid = y_pred[valid_mask]

    n = len(y_pred_valid)
    coverage = len(y_pred_valid) / len(y_true)

    # MAE
    mae = mean_absolute_error(y_true_valid, y_pred_valid)

    # RMSE
    rmse = np.sqrt(mean_squared_error(y_true_valid, y_pred_valid))

    # Brier Score
    brier = np.mean((y_true_valid - y_pred_valid) ** 2)

    # Log Loss (clip to avoid log(0))
    y_pred_clipped = np.clip(y_pred_valid, 0.001, 0.999)
    logloss = log_loss(y_true_valid, y_pred_clipped)

    # Calibration slope (regression of actual on predicted)
    mean_pred = np.mean(y_pred_valid)
    mean_actual = np.mean(y_true_valid)

    cov = np.mean((y_pred_valid - mean_pred) * (y_true_valid - mean_actual))
    var_pred = np.var(y_pred_valid)

    calibration_slope = cov / var_pred if var_pred > 0 else 0.0

    # Correlation
    var_actual = np.var(y_true_valid)
    correlation = cov / np.sqrt(var_pred * var_actual) if var_pred > 0 and var_actual > 0 else 0.0

    return {
        'model': model_name,
        'n': n,
        'coverage': coverage,
        'mae': mae,
        'rmse': rmse,
        'brier': brier,
        'log_loss': logloss,
        'calibration_slope': calibration_slope,
        'correlation': correlation,
        'mean_pred': mean_pred,
        'mean_actual': mean_actual
    }


def compute_calibration_by_decile(y_true, y_pred, bins=10):
    """Compute calibration by prediction decile."""
    df = pd.DataFrame({'y_true': y_true, 'y_pred': y_pred})
    df = df.dropna()

    df['decile'] = pd.qcut(df['y_pred'], q=bins, labels=False, duplicates='drop')

    calib = df.groupby('decile').agg({
        'y_pred': 'mean',
        'y_true': 'mean',
        'y_pred': 'count'
    }).rename(columns={'y_pred': 'mean_pred', 'y_true': 'mean_actual'})

    # Fix column naming issue from duplicate agg
    calib.columns = ['mean_pred', 'mean_actual', 'count']

    return calib


def aggregate_to_game_level(df):
    """Aggregate PA-level predictions to game-level for comparison."""
    print(f"\n[5] Aggregating to game-level (min {MIN_BF} BF)...")

    # Group by (game_pk, pitcher)
    game_level = df.groupby(['game_pk', 'pitcher']).agg({
        'is_k': 'sum',  # Actual strikeouts
        'type_pred_k': 'sum',  # Type-based predicted Ks
        'arch_pred_k': 'sum',  # Archetype predicted Ks
        'pitcher': 'count'  # Batters faced
    }).rename(columns={'pitcher': 'bf'})

    # Filter to starts (min BF)
    game_level = game_level[game_level['bf'] >= MIN_BF]

    print(f"  Games (starts): {len(game_level)}")

    return game_level


def plot_calibration(y_true, y_pred_arch, y_pred_type, save_path):
    """Generate side-by-side calibration plots."""
    print(f"\n[6] Generating calibration plots...")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Define bins
    bins = [0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 1.0]

    # Archetype model
    df_arch = pd.DataFrame({'y_true': y_true, 'y_pred': y_pred_arch}).dropna()
    df_arch['bin'] = pd.cut(df_arch['y_pred'], bins=bins)
    calib_arch = df_arch.groupby('bin', observed=True).agg(
        mean_pred=('y_pred', 'mean'),
        mean_actual=('y_true', 'mean'),
        n=('y_pred', 'count')
    )

    axes[0].plot([0, 1], [0, 1], 'k--', alpha=0.3, label='Perfect calibration')
    axes[0].scatter(calib_arch['mean_pred'], calib_arch['mean_actual'],
                    s=calib_arch['n']/50, alpha=0.6, color='blue')

    for idx, row in calib_arch.iterrows():
        axes[0].annotate(f"n={row['n']}", (row['mean_pred'], row['mean_actual']),
                         fontsize=8, alpha=0.7)

    axes[0].set_xlabel('Predicted K Rate')
    axes[0].set_ylabel('Actual K Rate')
    axes[0].set_title('Archetype Model Calibration')
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    # Type-based model
    df_type = pd.DataFrame({'y_true': y_true, 'y_pred': y_pred_type}).dropna()
    df_type['bin'] = pd.cut(df_type['y_pred'], bins=bins)
    calib_type = df_type.groupby('bin', observed=True).agg(
        mean_pred=('y_pred', 'mean'),
        mean_actual=('y_true', 'mean'),
        n=('y_pred', 'count')
    )

    axes[1].plot([0, 1], [0, 1], 'k--', alpha=0.3, label='Perfect calibration')
    axes[1].scatter(calib_type['mean_pred'], calib_type['mean_actual'],
                    s=calib_type['n']/50, alpha=0.6, color='green')

    for idx, row in calib_type.iterrows():
        axes[1].annotate(f"n={row['n']}", (row['mean_pred'], row['mean_actual']),
                         fontsize=8, alpha=0.7)

    axes[1].set_xlabel('Predicted K Rate')
    axes[1].set_ylabel('Actual K Rate')
    axes[1].set_title('Type-Based Model Calibration')
    axes[1].grid(alpha=0.3)
    axes[1].legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    print(f"  Saved to {save_path}")


def generate_comparison_report(metrics_arch, metrics_type, metrics_baseline, game_metrics, output_path):
    """Generate comprehensive comparison report."""
    print(f"\n[7] Generating comparison report...")

    report = []
    report.append("=" * 100)
    report.append("ARCHETYPE vs TYPE-BASED MODEL: HEAD-TO-HEAD COMPARISON")
    report.append("=" * 100)
    report.append(f"\nTest Set: {TEST_YEAR} ({metrics_arch['n']:,} PAs)")
    report.append(f"Training: {TRAIN_YEARS}")
    report.append(f"Shrinkage (Type model): {SHRINKAGE}")

    report.append("\n" + "=" * 100)
    report.append("PA-LEVEL METRICS")
    report.append("=" * 100)

    # Comparison table
    report.append(f"\n{'Metric':<20} {'Archetype':<15} {'Type-Based':<15} {'Winner':<15}")
    report.append("-" * 70)

    def compare_metric(name, arch_val, type_val, lower_is_better=True, is_pct=False):
        if is_pct:
            arch_str = f"{arch_val:.1%}"
            type_str = f"{type_val:.1%}"
        else:
            arch_str = f"{arch_val:.4f}"
            type_str = f"{type_val:.4f}"

        if lower_is_better:
            winner = "Archetype" if arch_val < type_val else "Type-Based"
        else:
            winner = "Archetype" if arch_val > type_val else "Type-Based"

        report.append(f"{name:<20} {arch_str:<15} {type_str:<15} {winner:<15}")

    compare_metric("Coverage", metrics_arch['coverage'], metrics_type['coverage'], lower_is_better=False, is_pct=True)
    compare_metric("MAE", metrics_arch['mae'], metrics_type['mae'], lower_is_better=True)
    compare_metric("RMSE", metrics_arch['rmse'], metrics_type['rmse'], lower_is_better=True)
    compare_metric("Brier Score", metrics_arch['brier'], metrics_type['brier'], lower_is_better=True)
    compare_metric("Log Loss", metrics_arch['log_loss'], metrics_type['log_loss'], lower_is_better=True)
    compare_metric("Calibration Slope", metrics_arch['calibration_slope'], metrics_type['calibration_slope'],
                   lower_is_better=False)  # Closer to 1.0 is better
    compare_metric("Correlation", metrics_arch['correlation'], metrics_type['correlation'], lower_is_better=False)

    # vs Baseline
    report.append(f"\n{'Baseline (League Avg)':<20} {metrics_baseline['mae']:.4f}")

    arch_improve = 100 * (metrics_baseline['mae'] - metrics_arch['mae']) / metrics_baseline['mae']
    type_improve = 100 * (metrics_baseline['mae'] - metrics_type['mae']) / metrics_baseline['mae']

    report.append(f"\nMAE Improvement vs Baseline:")
    report.append(f"  Archetype: {arch_improve:+.1f}%")
    report.append(f"  Type-Based: {type_improve:+.1f}%")

    # Game-level metrics
    report.append("\n" + "=" * 100)
    report.append("GAME-LEVEL METRICS (Starts with min 12 BF)")
    report.append("=" * 100)

    report.append(f"\n{'Metric':<20} {'Archetype':<15} {'Type-Based':<15} {'Winner':<15}")
    report.append("-" * 70)

    compare_metric("MAE (game-level)", game_metrics['arch']['mae'], game_metrics['type']['mae'],
                   lower_is_better=True)
    compare_metric("RMSE (game-level)", game_metrics['arch']['rmse'], game_metrics['type']['rmse'],
                   lower_is_better=True)
    compare_metric("Correlation", game_metrics['arch']['correlation'], game_metrics['type']['correlation'],
                   lower_is_better=False)

    # Interpretation
    report.append("\n" + "=" * 100)
    report.append("INTERPRETATION")
    report.append("=" * 100)

    report.append(f"""
PA-Level Performance:
  - Archetype MAE {metrics_arch['mae']:.4f} means avg error of {metrics_arch['mae']*100:.1f}pp per PA
  - Type-Based MAE {metrics_type['mae']:.4f} means avg error of {metrics_type['mae']*100:.1f}pp per PA
  - For 27 BF start, expected error: Archetype={metrics_arch['mae']*27:.2f}K, Type={metrics_type['mae']*27:.2f}K

Calibration:
  - Archetype slope {metrics_arch['calibration_slope']:.3f} (1.0 = perfect)
  - Type-Based slope {metrics_type['calibration_slope']:.3f}
  - {"Archetype" if abs(1.0 - metrics_arch['calibration_slope']) < abs(1.0 - metrics_type['calibration_slope']) else "Type-Based"} is better calibrated

Coverage:
  - Archetype: {metrics_arch['coverage']:.1%} (uses archetype method when available, fallback otherwise)
  - Type-Based: {metrics_type['coverage']:.1%} (always has prediction via shrinkage)
""")

    # Recommendation
    report.append("\n" + "=" * 100)
    report.append("RECOMMENDATION")
    report.append("=" * 100)

    # Determine winner based on MAE (primary metric)
    arch_wins_pa = metrics_arch['mae'] < metrics_type['mae']
    arch_wins_game = game_metrics['arch']['mae'] < game_metrics['type']['mae']

    if arch_wins_pa and arch_wins_game:
        recommendation = "USE ARCHETYPE MODEL"
        reason = "wins on both PA-level and game-level MAE"
    elif not arch_wins_pa and not arch_wins_game:
        recommendation = "USE TYPE-BASED MODEL"
        reason = "wins on both PA-level and game-level MAE"
    else:
        recommendation = "CONSIDER ENSEMBLE"
        reason = "models have complementary strengths"

    report.append(f"\n{recommendation}")
    report.append(f"Reason: {reason}\n")

    if recommendation == "CONSIDER ENSEMBLE":
        report.append("Ensemble strategies:")
        report.append("  1. Weighted average (tune weights on validation set)")
        report.append("  2. Use archetype when available (high coverage), fallback to type-based")
        report.append("  3. Meta-model: train on both predictions + features")

    report.append("\n" + "=" * 100)

    # Write report
    report_text = "\n".join(report)

    with open(output_path, 'w') as f:
        f.write(report_text)

    print(f"  Saved to {output_path}")

    return report_text


def main():
    print("=" * 100)
    print("ARCHETYPE vs TYPE-BASED MODEL: A/B TEST")
    print("=" * 100)

    # Connect to database
    con = duckdb.connect(DB, read_only=True)

    # Load test PA data
    test_pa = load_test_pa_data(con)

    # Build type-based model
    cell_k_rate, league_rate = build_type_model(con)

    # Get type-based predictions
    test_with_type = get_type_predictions(con, test_pa, cell_k_rate)

    # Get archetype predictions
    test_with_both = get_archetype_predictions(test_with_type)

    con.close()

    # Compute PA-level metrics
    y_true = test_with_both['is_k'].values
    y_pred_arch = test_with_both['arch_pred_k'].values
    y_pred_type = test_with_both['type_pred_k'].values

    metrics_arch = compute_metrics(y_true, y_pred_arch, "Archetype")
    metrics_type = compute_metrics(y_true, y_pred_type, "Type-Based")

    # Baseline: league average
    y_pred_baseline = np.full_like(y_true, league_rate, dtype=float)
    metrics_baseline = compute_metrics(y_true, y_pred_baseline, "Baseline")

    # Aggregate to game-level
    game_level = aggregate_to_game_level(test_with_both)

    # Game-level metrics
    game_metrics = {
        'arch': {
            'mae': mean_absolute_error(game_level['is_k'], game_level['arch_pred_k']),
            'rmse': np.sqrt(mean_squared_error(game_level['is_k'], game_level['arch_pred_k'])),
            'correlation': np.corrcoef(game_level['is_k'], game_level['arch_pred_k'])[0, 1]
        },
        'type': {
            'mae': mean_absolute_error(game_level['is_k'], game_level['type_pred_k']),
            'rmse': np.sqrt(mean_squared_error(game_level['is_k'], game_level['type_pred_k'])),
            'correlation': np.corrcoef(game_level['is_k'], game_level['type_pred_k'])[0, 1]
        }
    }

    # Generate calibration plot
    plot_calibration(y_true, y_pred_arch, y_pred_type, 'analytics/archetype_vs_type_calibration.png')

    # Generate comparison report
    report = generate_comparison_report(
        metrics_arch, metrics_type, metrics_baseline, game_metrics,
        'analytics/archetype_vs_type_comparison.txt'
    )

    # Print summary to console
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(report)


if __name__ == '__main__':
    main()
