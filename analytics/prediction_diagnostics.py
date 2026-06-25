"""Deep diagnostic analysis of prediction quality — NO BETTING.

Breaks down prediction accuracy by:
  - Prediction confidence level
  - Actual outcome buckets
  - Error distribution
  - Calibration curves
  - Reliability diagrams

Run: python prediction_diagnostics.py
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


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print("="* 80)
    print("PREDICTION DIAGNOSTICS (NO BOOKMAKER EDGE)")
    print(f"Train: {TRAIN}, Test: {TEST}, Min BF: {MIN_BF}")
    print("="* 80)

    # ---- Build model (same as pure_prediction_test.py) ----
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

    # ---- Get test predictions ----
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

    # ---- DIAGNOSTIC 1: Error distribution ----
    print("\n1. ERROR DISTRIBUTION")
    print("-" * 80)
    errors = [pred - actual for pred, actual in predictions]
    errors_sorted = sorted(errors)
    n = len(errors)

    percentiles = [10, 25, 50, 75, 90]
    print(f"{'Percentile':<15} {'Error (pred - actual)':<25}")
    for p in percentiles:
        idx = int(n * p / 100)
        print(f"{p:>3}th{'':<10} {errors_sorted[idx]:>10.2f}")

    abs_errors = sorted([abs(e) for e in errors])
    print(f"\nAbsolute errors:")
    for p in percentiles:
        idx = int(n * p / 100)
        print(f"{p:>3}th{'':<10} {abs_errors[idx]:>10.2f}")

    # ---- DIAGNOSTIC 2: Accuracy by prediction level ----
    print("\n\n2. ACCURACY BY PREDICTION LEVEL")
    print("-" * 80)

    buckets = defaultdict(list)
    for pred, actual in predictions:
        bucket = int(pred)  # 0-1, 1-2, 2-3, etc
        buckets[bucket].append((pred, actual))

    print(f"{'Predicted K':<15} {'N':<8} {'Mean Pred':<12} {'Mean Actual':<12} "
          f"{'MAE':<10} {'Bias':<10}")
    print("-" * 80)

    for bucket in sorted(buckets.keys()):
        preds = buckets[bucket]
        n_bucket = len(preds)
        mean_pred = sum(p for p, _ in preds) / n_bucket
        mean_actual = sum(a for _, a in preds) / n_bucket
        mae = sum(abs(p - a) for p, a in preds) / n_bucket
        bias = mean_pred - mean_actual

        print(f"{bucket}-{bucket+1}{'':<7} {n_bucket:<8} {mean_pred:<12.3f} "
              f"{mean_actual:<12.3f} {mae:<10.3f} {bias:>+10.3f}")

    # ---- DIAGNOSTIC 3: Calibration by decile ----
    print("\n\n3. CALIBRATION BY DECILE")
    print("-" * 80)
    print("(Are high predictions actually higher outcomes?)")

    sorted_preds = sorted(predictions, key=lambda x: x[0])
    decile_size = len(sorted_preds) // 10

    print(f"{'Decile':<10} {'N':<8} {'Mean Pred':<12} {'Mean Actual':<12} "
          f"{'Diff':<10}")
    print("-" * 80)

    for i in range(10):
        start_idx = i * decile_size
        end_idx = start_idx + decile_size if i < 9 else len(sorted_preds)
        decile = sorted_preds[start_idx:end_idx]

        n_dec = len(decile)
        mean_pred = sum(p for p, _ in decile) / n_dec
        mean_actual = sum(a for _, a in decile) / n_dec
        diff = mean_pred - mean_actual

        print(f"{i+1}{'':<9} {n_dec:<8} {mean_pred:<12.3f} {mean_actual:<12.3f} "
              f"{diff:>+10.3f}")

    # ---- DIAGNOSTIC 4: Overconfidence check ----
    print("\n\n4. OVERCONFIDENCE / UNDERCONFIDENCE")
    print("-" * 80)

    pred_spread = sorted([p for p, _ in predictions])
    actual_spread = sorted([a for _, a in predictions])

    print(f"{'Metric':<20} {'Predictions':<15} {'Actuals':<15} {'Ratio':<10}")
    print("-" * 80)

    pred_std = math.sqrt(sum((p - sum(pred_spread)/len(pred_spread))**2
                             for p in pred_spread) / len(pred_spread))
    actual_std = math.sqrt(sum((a - sum(actual_spread)/len(actual_spread))**2
                               for a in actual_spread) / len(actual_spread))

    pred_range = pred_spread[-1] - pred_spread[0]
    actual_range = actual_spread[-1] - actual_spread[0]

    print(f"{'Std Dev':<20} {pred_std:<15.3f} {actual_std:<15.3f} "
          f"{pred_std/actual_std:<10.3f}")
    print(f"{'Range (max-min)':<20} {pred_range:<15.3f} {actual_range:<15.3f} "
          f"{pred_range/actual_range:<10.3f}")
    print(f"\nRatio > 1.0 = overconfident (predictions spread too wide)")
    print(f"Ratio < 1.0 = underconfident (predictions too compressed)")

    # ---- SUMMARY ----
    print("\n\n" + "="* 80)
    print("SUMMARY")
    print("="* 80)
    mae_all = sum(abs(p - a) for p, a in predictions) / len(predictions)
    bias_all = sum(p - a for p, a in predictions) / len(predictions)

    print(f"Total predictions: {len(predictions)}")
    print(f"Overall MAE: {mae_all:.3f}")
    print(f"Overall Bias: {bias_all:+.3f} (positive = overpredicting)")
    print(f"\nThis analysis is INDEPENDENT of any betting strategy.")


if __name__ == "__main__":
    main()
