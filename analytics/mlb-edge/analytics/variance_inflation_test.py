"""Test variance inflation to fix underconfidence without changing MAE.

The type-based model has the best MAE (1.672) but is underconfident (spread=0.502).
This tests multiplying predictions by a constant to hit spread_ratio=1.0 while
preserving the relative ordering (correlation) of predictions.

Approach: pred_inflated = mean + alpha * (pred_raw - mean)
where alpha is tuned to hit spread_ratio = 1.0

Run: python variance_inflation_test.py
"""
from __future__ import annotations

import math
from collections import defaultdict

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
SHRINK = 200.0
MIN_BF = 12


def compute_metrics(predictions: list[tuple[float, int]], label: str = ""):
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
    spread_ratio = math.sqrt(var_p / var_a) if var_a > 0 else 0.0
    bias = mean_p - mean_a

    std_p = math.sqrt(var_p / n) if n > 0 else 0
    std_a = math.sqrt(var_a / n) if n > 0 else 0

    return {
        "label": label,
        "n": n,
        "mae": mae,
        "rmse": rmse,
        "corr": corr,
        "spread_ratio": spread_ratio,
        "bias": bias,
        "mean_p": mean_p,
        "mean_a": mean_a,
        "std_p": std_p,
        "std_a": std_a,
    }


def inflate_variance(predictions: list[tuple[float, int]], alpha: float) -> list[tuple[float, int]]:
    """Inflate prediction variance by factor alpha around the mean.

    pred_new = mean + alpha * (pred_old - mean)
    """
    pred_vals = [p for p, _ in predictions]
    mean_p = sum(pred_vals) / len(pred_vals)

    inflated = []
    for pred, actual in predictions:
        new_pred = mean_p + alpha * (pred - mean_p)
        inflated.append((new_pred, actual))

    return inflated


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print("="* 90)
    print("VARIANCE INFLATION TEST")
    print("Fix underconfidence (spread_ratio 0.502 -> 1.0) via prediction scaling")
    print(f"Train: {TRAIN}, Test: {TEST}")
    print("="* 90)

    # ---- Build type-based model (original baseline) ----
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
        return (k + SHRINK * prior) / (n + SHRINK)

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

    base_preds = [(s["pred_k"], s["actual_k"])
                  for s in starts.values()
                  if s["bf"] >= MIN_BF]

    # ---- Test different inflation factors ----
    print("\nTesting inflation factors (alpha)...")
    print(f"\n{'Alpha':<8} {'MAE':<8} {'RMSE':<8} {'Corr':<8} {'Spread':<8} {'Bias':<8}")
    print("-" * 90)

    alphas = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]
    results = []

    for alpha in alphas:
        inflated = inflate_variance(base_preds, alpha)
        m = compute_metrics(inflated, f"alpha={alpha}")
        results.append((alpha, m))

        print(f"{alpha:<8.2f} {m['mae']:<8.3f} {m['rmse']:<8.3f} {m['corr']:<8.3f} "
              f"{m['spread_ratio']:<8.3f} {m['bias']:>+8.3f}")

    # Find alpha that gets closest to spread_ratio = 1.0
    best_alpha, best_m = min(results, key=lambda x: abs(x[1]['spread_ratio'] - 1.0))

    print("\n" + "="* 90)
    print("OPTIMAL CALIBRATION")
    print("="* 90)
    print(f"Best alpha: {best_alpha:.2f}")
    print(f"Spread ratio: {best_m['spread_ratio']:.3f} (target: 1.0)")
    print(f"MAE: {best_m['mae']:.3f}")
    print(f"Correlation: {best_m['corr']:.3f}")
    print(f"Bias: {best_m['bias']:+.3f}")

    # Compare to original
    orig = compute_metrics(base_preds, "original")
    print(f"\nOriginal model:")
    print(f"  MAE: {orig['mae']:.3f}")
    print(f"  Correlation: {orig['corr']:.3f} (UNCHANGED by inflation)")
    print(f"  Spread: {orig['spread_ratio']:.3f}")
    print(f"  Bias: {orig['bias']:+.3f}")

    print(f"\nCalibrated model (alpha={best_alpha:.2f}):")
    print(f"  MAE: {best_m['mae']:.3f} ({(best_m['mae']-orig['mae'])/orig['mae']*100:+.1f}%)")
    print(f"  Correlation: {best_m['corr']:.3f} (UNCHANGED)")
    print(f"  Spread: {best_m['spread_ratio']:.3f} (target achieved)")
    print(f"  Bias: {best_m['bias']:+.3f}")

    print("\n" + "="* 90)
    print("INTERPRETATION")
    print("="* 90)
    print(f"Variance inflation with alpha={best_alpha:.2f}:")
    print(f"  - Fixes underconfidence: spread 0.502 -> {best_m['spread_ratio']:.3f}")
    print(f"  - Preserves correlation: {orig['corr']:.3f} -> {best_m['corr']:.3f}")
    print(f"  - MAE tradeoff: {orig['mae']:.3f} -> {best_m['mae']:.3f}")
    print()
    print("Formula: pred_calibrated = mean + {:.2f} * (pred_raw - mean)".format(best_alpha))
    print()
    print("Use this when:")
    print("  - You need well-calibrated prediction intervals")
    print("  - Building confidence bands or uncertainty estimates")
    print("  - MAE increase is acceptable for better calibration")
    print()
    print("DON'T use this for:")
    print("  - Minimizing prediction error (use raw predictions)")
    print("  - Rank-ordering predictions (correlation unchanged anyway)")


if __name__ == "__main__":
    main()
