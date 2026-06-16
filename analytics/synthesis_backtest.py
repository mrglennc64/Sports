"""Synthesis experiment — can individual + type together beat either alone?

backtest_matchup.py showed (OOS, train 2024-25 -> test 2026 starts):
  matchup (type x type)  MAE 1.672  (best)
  pitcher-type only      MAE 1.686
  pitcher-individual     MAE 1.722  (overfits — worse than type)

Hypothesis: the right combination is the type MATCHUP as a robust base, PLUS each
pitcher's individual deviation from his archetype, shrunk by his sample size:

    rate(pitcher i vs batter-type b) = cell(p_type, b)
                                       + (n_i / (n_i + K)) * (indiv_i - pmarg[p_type])

High-sample aces get their personal edge added; low-sample arms stay at the robust
type-matchup rate. Sweep K to find the best shrink, compare to matchup-alone.

    python synthesis_backtest.py
"""
from __future__ import annotations

from collections import defaultdict

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
CELL_SHRINK = 200.0
MIN_BF = 12
K_SWEEP = [200, 800, 1600, 3200, 6400, 12800, 25600]


def main() -> None:
    con = duckdb.connect(DB)

    # cell + pitcher-type marginals (train)
    tr = con.execute(f"""
        SELECT pit.cluster_v2 p, bat.cluster_v2 b, count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
        WHERE e.season IN {TRAIN} GROUP BY 1,2
    """).fetchall()
    cell_n, cell_k = {}, {}
    pmarg_n, pmarg_k = defaultdict(int), defaultdict(int)
    tot_n = tot_k = 0
    for p, b, n, k in tr:
        if p is None or b is None:
            continue
        cell_n[(p, b)] = n; cell_k[(p, b)] = k
        pmarg_n[p] += n; pmarg_k[p] += k; tot_n += n; tot_k += k
    league = tot_k / tot_n
    pmarg = {p: pmarg_k[p] / pmarg_n[p] for p in pmarg_n}

    def cell_rate(p, b):
        if p is None:
            return league
        prior = pmarg.get(p, league)
        if b is None or (p, b) not in cell_n:
            return prior
        n, k = cell_n[(p, b)], cell_k[(p, b)]
        return (k + CELL_SHRINK * prior) / (n + CELL_SHRINK)

    # individual pitcher rate + sample size (train)
    ind = con.execute(f"""
        SELECT e.pitcher, pit.cluster_v2 p, count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        WHERE e.season IN {TRAIN} GROUP BY 1,2
    """).fetchall()
    indiv = {pid: (n, k / n, p) for pid, p, n, k in ind}  # id -> (n_i, rate_i, type)

    rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, pit.cluster_v2 p, bat.cluster_v2 b, e.events
        FROM pa_events_reg e
        LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season={TEST}
        LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season={TEST}
        WHERE e.season={TEST}
    """).fetchall()
    con.close()

    # group PAs into starts once; precompute the type-matchup base per PA
    starts = defaultdict(lambda: {"bf": 0, "actual": 0, "matchup": 0.0, "pas": []})
    for gpk, pid, p, b, events in rows:
        s = starts[(gpk, pid)]
        s["bf"] += 1
        s["actual"] += 1 if (events and events.startswith("strikeout")) else 0
        base = cell_rate(p, b)
        s["matchup"] += base
        # store (base, pitcher dev pieces) for the synthesis sweep
        s["pas"].append((pid, p, base))

    sel = [s for s in starts.values() if s["bf"] >= MIN_BF]
    n = len(sel)

    def mae_corr(pred, act):
        mae = sum(abs(pred[i] - act[i]) for i in range(n)) / n
        mp, ma = sum(pred) / n, sum(act) / n
        cov = sum((pred[i]-mp)*(act[i]-ma) for i in range(n))
        vp = sum((v-mp)**2 for v in pred) ** 0.5
        va = sum((v-ma)**2 for v in act) ** 0.5
        return mae, (cov/(vp*va) if vp and va else 0.0)

    act = [s["actual"] for s in sel]
    base_pred = [s["matchup"] for s in sel]
    bmae, bcorr = mae_corr(base_pred, act)
    print(f"Train {TRAIN} -> Test {TEST}.  starts={n}\n")
    print(f"matchup-alone (baseline):   MAE {bmae:.4f}  corr {bcorr:.3f}\n")
    print(f"{'K_synth':>8}{'MAE':>9}{'corr':>8}{'vs matchup':>13}")
    print("-" * 38)
    best = None
    for K in K_SWEEP:
        pred = []
        for s in sel:
            tot = 0.0
            for pid, p, base in s["pas"]:
                if pid in indiv and p is not None:
                    n_i, r_i, _ = indiv[pid]
                    dev = r_i - pmarg.get(p, league)
                    rate = base + (n_i / (n_i + K)) * dev
                else:
                    rate = base
                tot += min(1.0, max(0.0, rate))
            pred.append(tot)
        mae, corr = mae_corr(pred, act)
        d = bmae - mae
        flag = ""
        if best is None or mae < best[1]:
            best = (K, mae, corr)
        print(f"{K:>8}{mae:9.4f}{corr:8.3f}{d:+12.4f}{'  <- best' if best[0]==K else ''}")
    print(f"\nbest synthesis: K={best[0]}  MAE {best[1]:.4f}  corr {best[2]:.3f}"
          f"   ({100*(bmae-best[1])/bmae:+.2f}% vs matchup-alone)")


if __name__ == "__main__":
    main()
