"""Experiment with different empirical Bayes shrinkage levels to optimize
pure prediction accuracy (no betting context).

Tests multiple SHRINK values to find the sweet spot between:
  - Too much shrinkage = underconfident, compressed predictions
  - Too little shrinkage = overfit to noise, high variance

Run: python tune_shrinkage.py
"""
from __future__ import annotations

import math
from collections import defaultdict

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
MIN_BF = 12

# Test these shrinkage values
SHRINK_VALUES = [0, 25, 50, 100, 150, 200, 300, 500, 1000]


def compute_metrics(predictions: list[tuple[float, int]]):
    """Quick metrics computation."""
    n = len(predictions)
    pred = [p for p, _ in predictions]
    actual = [a for _, a in predictions]

    mae = sum(abs(p - a) for p, a in predictions) / n
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in predictions) / n)

    mean_p = sum(pred) / n
    mean_a = sum(actual) / n

    cov = sum((pred[i] - mean_p) * (actual[i] - mean_a) for i in range(n))
    var_p = sum((p - mean_p) ** 2 for p in pred)
    var_a = sum((a - mean_a) ** 2 for a in actual)

    corr = cov / math.sqrt(var_p * var_a) if var_p > 0 and var_a > 0 else 0.0
    cal_slope = cov / var_a if var_a > 0 else 0.0

    spread_ratio = math.sqrt(var_p / var_a) if var_a > 0 else 0.0
    bias = mean_p - mean_a

    return {
        "mae": mae,
        "rmse": rmse,
        "corr": corr,
        "cal_slope": cal_slope,
        "spread_ratio": spread_ratio,
        "bias": bias,
    }


def test_shrinkage(shrink: float) -> dict:
    """Test a specific shrinkage value."""
    con = duckdb.connect(DB, read_only=True)

    # Train rates
    tr = con.execute(f"""
        SELECT pit.cluster_v2 AS p, bat.cluster_v2 AS b,
               count(*) n, count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
        WHERE e.season IN {TRAIN}
        GROUP BY 1,2
    """).fetchall()

    cell_n, cell_k = {}, {}
    pmarg_n, pmarg_k = defaultdict(int), defaultdict(int)
    tot_n = tot_k = 0

    for p, b, n, k in tr:
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

    def cell_k_rate(p, b):
        if p is None:
            return league_rate
        prior = pmarg_rate.get(p, league_rate)
        if b is None or (p, b) not in cell_n:
            return prior
        n, k = cell_n[(p, b)], cell_k[(p, b)]
        if shrink == 0:  # no shrinkage = MLE
            return k / n if n > 0 else prior
        return (k + shrink * prior) / (n + shrink)

    # Test predictions
    rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, pit.cluster_v2 AS p, bat.cluster_v2 AS b,
               CASE WHEN e.events LIKE 'strikeout%' THEN 1 ELSE 0 END AS is_k
        FROM pa_events_reg e
        LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season={TEST}
        LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season={TEST}
        WHERE e.season={TEST}
    """).fetchall()
    con.close()

    starts = defaultdict(lambda: {"pred_k": 0.0, "actual_k": 0, "bf": 0})
    for gpk, pid, p, b, is_k in rows:
        key = (gpk, pid)
        starts[key]["pred_k"] += cell_k_rate(p, b)
        starts[key]["actual_k"] += is_k
        starts[key]["bf"] += 1

    predictions = [(s["pred_k"], s["actual_k"])
                   for s in starts.values()
                   if s["bf"] >= MIN_BF]

    return compute_metrics(predictions)


def main() -> None:
    print("="* 90)
    print("EMPIRICAL BAYES SHRINKAGE TUNING")
    print("Testing different shrinkage strengths for optimal pure prediction accuracy")
    print(f"Train: {TRAIN}, Test: {TEST}")
    print("="* 90)

    print(f"\n{'Shrink':<8} {'MAE':<8} {'RMSE':<8} {'Corr':<8} {'Spread':<8} "
          f"{'CalSlope':<10} {'Bias':<8}")
    print("-" * 90)

    results = []
    for shrink in SHRINK_VALUES:
        metrics = test_shrinkage(shrink)
        results.append((shrink, metrics))

        print(f"{shrink:<8.0f} {metrics['mae']:<8.3f} {metrics['rmse']:<8.3f} "
              f"{metrics['corr']:<8.3f} {metrics['spread_ratio']:<8.3f} "
              f"{metrics['cal_slope']:<10.3f} {metrics['bias']:>+8.3f}")

    print("\n" + "="* 90)
    print("INTERPRETATION:")
    print("-" * 90)

    # Find best by different metrics
    best_mae = min(results, key=lambda x: x[1]['mae'])
    best_corr = max(results, key=lambda x: x[1]['corr'])
    best_spread = min(results, key=lambda x: abs(x[1]['spread_ratio'] - 1.0))
    best_bias = min(results, key=lambda x: abs(x[1]['bias']))

    print(f"Best MAE:         shrink={best_mae[0]:<6.0f}  (MAE={best_mae[1]['mae']:.3f})")
    print(f"Best Correlation: shrink={best_corr[0]:<6.0f}  (r={best_corr[1]['corr']:.3f})")
    print(f"Best Spread:      shrink={best_spread[0]:<6.0f}  "
          f"(ratio={best_spread[1]['spread_ratio']:.3f}, want 1.0)")
    print(f"Least Bias:       shrink={best_bias[0]:<6.0f}  "
          f"(bias={best_bias[1]['bias']:+.3f}, want 0.0)")

    print("\n" + "="* 90)
    print("RECOMMENDATIONS:")
    print("-" * 90)
    print(f"Current setting (SHRINK=200): MAE={results[5][1]['mae']:.3f}, "
          f"spread={results[5][1]['spread_ratio']:.3f}")
    print()

    if best_spread[0] < 200:
        print(f"⚠️  UNDERCONFIDENT: Try reducing shrinkage to {best_spread[0]:.0f}")
        print(f"    This will make predictions spread more like actual outcomes")
    elif best_spread[0] > 200:
        print(f"⚠️  OVERCONFIDENT: Try increasing shrinkage to {best_spread[0]:.0f}")
        print(f"    This will compress extreme predictions toward the mean")
    else:
        print(f"✅  Current shrinkage (200) is near optimal for spread calibration")

    print()
    print("Note: Spread ratio = how much predictions vary vs actuals")
    print("      1.0 = perfectly calibrated variance")
    print("      <1.0 = underconfident (predictions too compressed)")
    print("      >1.0 = overconfident (predictions too spread out)")


if __name__ == "__main__":
    main()
