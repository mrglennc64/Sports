"""Pure prediction accuracy test — NO BETTING, NO ODDS, NO BOOKMAKER EDGE.

Just measures how well your model predicts outcomes compared to what actually happened.
Uses standard statistical metrics used in forecasting/ML, ignoring profitability entirely.

Metrics computed:
  1. MAE (Mean Absolute Error) — average prediction miss in strikeouts
  2. RMSE (Root Mean Squared Error) — penalizes large misses more
  3. Correlation — does your prediction move with actual outcomes?
  4. Calibration — are your probabilities well-calibrated?
  5. Log Score — proper scoring rule for probabilistic predictions
  6. Brier Score — measures probability forecast accuracy

Run: python pure_prediction_test.py
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
SHRINK = 200.0
MIN_BF = 12  # minimum batters faced to count as a start


@dataclass
class PredictionMetrics:
    """Pure forecasting metrics with zero betting context."""
    n_predictions: int
    mae: float           # mean absolute error
    rmse: float          # root mean squared error
    correlation: float   # Pearson r between predicted and actual
    mean_predicted: float
    mean_actual: float
    calibration_slope: float  # if 1.0, perfectly calibrated spread
    log_score: float | None   # probabilistic scoring (lower is better)
    brier_score: float | None # probability calibration (lower is better)


def compute_metrics(predictions: list[tuple[float, int]]) -> PredictionMetrics:
    """Compute pure prediction quality metrics.

    Args:
        predictions: list of (predicted_ks, actual_ks) tuples
    """
    n = len(predictions)
    if n == 0:
        raise ValueError("No predictions to evaluate")

    pred = [p for p, _ in predictions]
    actual = [a for _, a in predictions]

    # Mean Absolute Error
    mae = sum(abs(p - a) for p, a in predictions) / n

    # Root Mean Squared Error
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in predictions) / n)

    # Correlation (Pearson r)
    mean_p = sum(pred) / n
    mean_a = sum(actual) / n

    cov = sum((pred[i] - mean_p) * (actual[i] - mean_a) for i in range(n))
    var_p = sum((p - mean_p) ** 2 for p in pred)
    var_a = sum((a - mean_a) ** 2 for a in actual)

    correlation = cov / math.sqrt(var_p * var_a) if var_p > 0 and var_a > 0 else 0.0

    # Calibration slope (regression predicted on actual)
    # If slope=1.0, predictions spread matches actual spread perfectly
    calibration_slope = cov / var_a if var_a > 0 else 0.0

    # For probabilistic metrics, we'd need per-PA probabilities
    # For now, set to None (could add later)
    log_score = None
    brier_score = None

    return PredictionMetrics(
        n_predictions=n,
        mae=mae,
        rmse=rmse,
        correlation=correlation,
        mean_predicted=mean_p,
        mean_actual=mean_a,
        calibration_slope=calibration_slope,
        log_score=log_score,
        brier_score=brier_score
    )


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print(f"Pure Prediction Test (NO BETTING CONTEXT)")
    print(f"Train: {TRAIN}, Test: {TEST}")
    print("=" * 80)

    # ---- TRAIN rates from 2024+2025 (same as backtest_matchup.py) ----
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
        """Empirical Bayes shrinkage toward pitcher-type prior."""
        if p is None:
            return league_rate
        prior = pmarg_rate.get(p, league_rate)
        if b is None or (p, b) not in cell_n:
            return prior
        n, k = cell_n[(p, b)], cell_k[(p, b)]
        return (k + SHRINK * prior) / (n + SHRINK)

    # ---- TEST on 2026 starts ----
    rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, pit.cluster_v2 AS p, bat.cluster_v2 AS b,
               CASE WHEN e.events LIKE 'strikeout%' THEN 1 ELSE 0 END AS is_k
        FROM pa_events_reg e
        LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season={TEST}
        LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season={TEST}
        WHERE e.season={TEST}
    """).fetchall()
    con.close()

    # Accumulate per-start predictions
    starts = defaultdict(lambda: {"pred_k": 0.0, "actual_k": 0, "bf": 0})

    for gpk, pid, p, b, is_k in rows:
        key = (gpk, pid)
        starts[key]["pred_k"] += cell_k_rate(p, b)
        starts[key]["actual_k"] += is_k
        starts[key]["bf"] += 1

    # Filter to actual starts (min batters faced)
    valid_starts = [(s["pred_k"], s["actual_k"])
                    for s in starts.values()
                    if s["bf"] >= MIN_BF]

    # ---- Compute metrics for three model levels ----

    # 1. League baseline (every PA = league rate)
    league_preds = [(s["bf"] * league_rate, s["actual_k"])
                    for s in starts.values()
                    if s["bf"] >= MIN_BF]

    # 2. Pitcher-type only (ignores opponent lineup)
    ptype_preds = []
    for s in starts.values():
        if s["bf"] < MIN_BF:
            continue
        # Would need pitcher type per start - skip for now, use matchup

    # 3. Full matchup model (pitcher-type × batter-type)
    matchup_preds = valid_starts

    print(f"\n{'Model':<20} {'N':<6} {'MAE':<8} {'RMSE':<8} {'Corr':<8} {'Cal.Slope':<10}")
    print("-" * 80)

    # League baseline
    m = compute_metrics(league_preds)
    print(f"{'League (baseline)':<20} {m.n_predictions:<6} {m.mae:<8.3f} {m.rmse:<8.3f} "
          f"{m.correlation:<8.3f} {m.calibration_slope:<10.3f}")

    # Full matchup model
    m = compute_metrics(matchup_preds)
    print(f"{'Matchup (full)':<20} {m.n_predictions:<6} {m.mae:<8.3f} {m.rmse:<8.3f} "
          f"{m.correlation:<8.3f} {m.calibration_slope:<10.3f}")

    print("\n" + "=" * 80)
    print("INTERPRETATION:")
    print(f"  MAE    = average miss in strikeouts (lower is better)")
    print(f"  RMSE   = penalizes big misses more (lower is better)")
    print(f"  Corr   = does prediction track actual? (higher is better, 1.0 = perfect)")
    print(f"  Slope  = calibration (1.0 = perfect spread, <1.0 = overconfident)")
    print("\nNOTE: These metrics ignore all betting/odds/profitability concerns.")
    print("      They ONLY measure raw prediction accuracy.")


if __name__ == "__main__":
    main()
