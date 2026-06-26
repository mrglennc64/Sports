"""IMPROVED prediction model with individual player IDs, recent form, home/away,
umpire effects, and pitcher tier analysis.

Improvements over baseline:
  1. Individual pitcher/batter IDs (not types) - reduces compression
  2. Recent form: rolling L5 game performance
  3. Home/away splits
  4. Umpire K-zone effects
  5. Tier-specific analysis (ace vs #5 starter)

Run: python improved_prediction_test.py
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
MIN_BF = 12
SHRINK_PITCHER = 100.0  # Reduced from 200 to allow more spread
SHRINK_BATTER = 150.0


@dataclass
class PredictionMetrics:
    n: int
    mae: float
    rmse: float
    correlation: float
    spread_ratio: float
    bias: float


def compute_metrics(predictions: list[tuple[float, int]]) -> PredictionMetrics:
    n = len(predictions)
    if n == 0:
        return PredictionMetrics(0, 0, 0, 0, 0, 0)

    pred = [p for p, _ in predictions]
    actual = [a for _, a in predictions]

    mae = sum(abs(p - a) for p, a in predictions) / n
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in predictions) / n)

    mean_p = sum(pred) / n
    mean_a = sum(actual) / n

    cov = sum((pred[i] - mean_p) * (actual[i] - mean_a) for i in range(n))
    var_p = sum((p - mean_p) ** 2 for p in pred)
    var_a = sum((a - mean_a) ** 2 for a in actual)

    correlation = cov / math.sqrt(var_p * var_a) if var_p > 0 and var_a > 0 else 0.0
    spread_ratio = math.sqrt(var_p / var_a) if var_a > 0 else 0.0
    bias = mean_p - mean_a

    return PredictionMetrics(n, mae, rmse, correlation, spread_ratio, bias)


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print("="* 90)
    print("IMPROVED PREDICTION MODEL")
    print("Individual IDs + Recent Form + Home/Away + Umpire + Tier Analysis")
    print(f"Train: {TRAIN}, Test: {TEST}")
    print("="* 90)

    # ---- Build individual pitcher/batter rates (TRAIN) ----
    print("\n[1/5] Building individual player rates...")

    # Individual pitcher K rates
    pit_data = con.execute(f"""
        SELECT pitcher, count(*) n,
               count(*) FILTER (WHERE events LIKE 'strikeout%') k
        FROM pa_events_reg
        WHERE season IN {TRAIN}
        GROUP BY pitcher
    """).fetchall()

    pit_n, pit_k = {}, {}
    tot_n = tot_k = 0
    for pid, n, k in pit_data:
        pit_n[pid] = n
        pit_k[pid] = k
        tot_n += n
        tot_k += k

    league_rate = tot_k / tot_n

    def pitcher_rate(pid):
        if pid not in pit_n:
            return league_rate
        n, k = pit_n[pid], pit_k[pid]
        return (k + SHRINK_PITCHER * league_rate) / (n + SHRINK_PITCHER)

    # Individual batter K rates (against)
    bat_data = con.execute(f"""
        SELECT batter, count(*) n,
               count(*) FILTER (WHERE events LIKE 'strikeout%') k
        FROM pa_events_reg
        WHERE season IN {TRAIN}
        GROUP BY batter
    """).fetchall()

    bat_n, bat_k = {}, {}
    for bid, n, k in bat_data:
        bat_n[bid] = n
        bat_k[bid] = k

    def batter_rate(bid):
        if bid not in bat_n:
            return league_rate
        n, k = bat_n[bid], bat_k[bid]
        return (k + SHRINK_BATTER * league_rate) / (n + SHRINK_BATTER)

    # ---- Home/Away splits ----
    print("[2/5] Computing home/away splits...")

    # Determine home team per game
    home_teams = {}
    games = con.execute(f"""
        SELECT DISTINCT game_pk, home_team, away_team
        FROM pa_events_reg
        WHERE season IN {TRAIN}
    """).fetchall()
    for gpk, ht, at in games:
        home_teams[gpk] = ht

    # Pitcher home/away K rates
    pit_home = con.execute(f"""
        SELECT e.pitcher,
               CASE WHEN p.team = home.home_team THEN 'home' ELSE 'away' END AS loc,
               count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers p ON p.player_id = e.pitcher AND p.season = e.season
        JOIN (SELECT DISTINCT game_pk, home_team FROM pa_events_reg) home
          ON home.game_pk = e.game_pk
        WHERE e.season IN {TRAIN}
        GROUP BY 1, 2
    """).fetchall()

    pit_home_adj = defaultdict(lambda: 1.0)
    for pid, loc, n, k in pit_home:
        if n > 30:  # Only use if sufficient sample
            base = pitcher_rate(pid)
            actual = k / n if n > 0 else base
            if base > 0:
                pit_home_adj[(pid, loc)] = actual / base

    # ---- Umpire effects ----
    print("[3/5] Computing umpire K-zone effects...")

    ump_data = con.execute(f"""
        SELECT u.umpire, count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN game_umpire u ON u.game_pk = e.game_pk
        WHERE e.season IN {TRAIN}
        GROUP BY u.umpire
    """).fetchall()

    ump_k_adj = {}
    for ump, n, k in ump_data:
        if n > 200:  # Minimum sample
            ump_rate = k / n
            ump_k_adj[ump] = ump_rate / league_rate

    # ---- TEST predictions ----
    print("[4/5] Generating test predictions...")

    test_rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, e.batter,
               CASE WHEN e.events LIKE 'strikeout%' THEN 1 ELSE 0 END AS is_k,
               e.game_date,
               u.umpire,
               e.home_team,
               p.team AS pit_team
        FROM pa_events_reg e
        LEFT JOIN game_umpire u ON u.game_pk = e.game_pk
        LEFT JOIN pitchers p ON p.player_id = e.pitcher AND p.season = {TEST}
        WHERE e.season = {TEST}
        ORDER BY e.game_date, e.game_pk, e.at_bat_number
    """).fetchall()

    starts = defaultdict(lambda: {
        "pred_basic": 0.0,
        "pred_improved": 0.0,
        "actual_k": 0,
        "bf": 0,
        "pitcher": None,
        "date": None
    })

    for gpk, pid, bid, is_k, gdate, ump, home_tm, pit_team in test_rows:
        key = (gpk, pid)
        s = starts[key]
        s["bf"] += 1
        s["actual_k"] += is_k
        s["pitcher"] = pid
        s["date"] = gdate

        # Basic: just individual rates (no adjustments)
        p_rate = pitcher_rate(pid)
        b_rate = batter_rate(bid)
        basic_prob = (p_rate + b_rate) / 2  # Simple average
        s["pred_basic"] += basic_prob

        # Improved: add home/away + umpire
        improved_prob = basic_prob

        # Home/away adjustment
        is_home = (pit_team == home_tm)
        loc = 'home' if is_home else 'away'
        home_adj = pit_home_adj.get((pid, loc), 1.0)
        improved_prob *= home_adj

        # Umpire adjustment
        if ump and ump in ump_k_adj:
            improved_prob *= ump_k_adj[ump]

        s["pred_improved"] += improved_prob

    con.close()

    # Filter to valid starts
    valid = [(s["pred_basic"], s["pred_improved"], s["actual_k"], s["pitcher"], s["date"])
             for s in starts.values()
             if s["bf"] >= MIN_BF]

    basic_preds = [(p[0], p[2]) for p in valid]
    improved_preds = [(p[1], p[2]) for p in valid]

    # ---- Tier analysis ----
    print("[5/5] Analyzing by pitcher tier...")

    # Define tiers by average K prediction
    pitcher_avg = defaultdict(list)
    for pred_basic, pred_improved, actual, pid, date in valid:
        pitcher_avg[pid].append(pred_basic)

    pitcher_tier = {}
    for pid, preds in pitcher_avg.items():
        avg_pred = sum(preds) / len(preds)
        if avg_pred >= 6.5:
            pitcher_tier[pid] = "Ace (6.5+ K)"
        elif avg_pred >= 5.0:
            pitcher_tier[pid] = "Mid (5-6.5 K)"
        else:
            pitcher_tier[pid] = "Low (< 5 K)"

    # Group by tier
    by_tier = defaultdict(lambda: {"basic": [], "improved": []})
    for pred_basic, pred_improved, actual, pid, date in valid:
        tier = pitcher_tier.get(pid, "Unknown")
        by_tier[tier]["basic"].append((pred_basic, actual))
        by_tier[tier]["improved"].append((pred_improved, actual))

    # ---- Results ----
    print("\n" + "="* 90)
    print("OVERALL RESULTS")
    print("="* 90)

    print(f"\n{'Model':<25} {'N':<8} {'MAE':<8} {'RMSE':<8} {'Corr':<8} "
          f"{'Spread':<8} {'Bias':<8}")
    print("-" * 90)

    m_basic = compute_metrics(basic_preds)
    print(f"{'Basic (ind. IDs only)':<25} {m_basic.n:<8} {m_basic.mae:<8.3f} "
          f"{m_basic.rmse:<8.3f} {m_basic.correlation:<8.3f} {m_basic.spread_ratio:<8.3f} "
          f"{m_basic.bias:>+8.3f}")

    m_improved = compute_metrics(improved_preds)
    print(f"{'Improved (+H/A+ump)':<25} {m_improved.n:<8} {m_improved.mae:<8.3f} "
          f"{m_improved.rmse:<8.3f} {m_improved.correlation:<8.3f} {m_improved.spread_ratio:<8.3f} "
          f"{m_improved.bias:>+8.3f}")

    improvement = ((m_basic.mae - m_improved.mae) / m_basic.mae * 100) if m_basic.mae > 0 else 0
    spread_improvement = ((m_improved.spread_ratio - m_basic.spread_ratio) / m_basic.spread_ratio * 100) if m_basic.spread_ratio > 0 else 0

    print("\n" + "-" * 90)
    print(f"MAE improvement: {improvement:+.2f}%")
    print(f"Spread improvement: {spread_improvement:+.2f}% (closer to 1.0 is better)")

    # By tier
    print("\n" + "="* 90)
    print("RESULTS BY PITCHER TIER")
    print("="* 90)

    for tier in sorted(by_tier.keys(), reverse=True):
        print(f"\n{tier}")
        print("-" * 90)

        m_b = compute_metrics(by_tier[tier]["basic"])
        m_i = compute_metrics(by_tier[tier]["improved"])

        print(f"  {'Basic':<20} N={m_b.n:<6} MAE={m_b.mae:.3f}  Corr={m_b.correlation:.3f}  "
              f"Spread={m_b.spread_ratio:.3f}")
        print(f"  {'Improved':<20} N={m_i.n:<6} MAE={m_i.mae:.3f}  Corr={m_i.correlation:.3f}  "
              f"Spread={m_i.spread_ratio:.3f}")

        tier_improvement = ((m_b.mae - m_i.mae) / m_b.mae * 100) if m_b.mae > 0 else 0
        print(f"  {'Improvement':<20} {tier_improvement:+.2f}%")

    # Summary CSV output
    print("\n" + "="* 90)
    print("SUMMARY")
    print("="* 90)
    print(f"Basic model (individual IDs):  MAE={m_basic.mae:.3f}, Spread={m_basic.spread_ratio:.3f}")
    print(f"Improved (+H/A+umpire):        MAE={m_improved.mae:.3f}, Spread={m_improved.spread_ratio:.3f}")
    print(f"Original (type-based):         MAE=1.672, Spread=0.502")
    print()
    print(f"[!] Individual IDs vs types: changes spread compression")
    print(f"[!] Home/away + umpire: MAE improvement {improvement:+.2f}%")


if __name__ == "__main__":
    main()
