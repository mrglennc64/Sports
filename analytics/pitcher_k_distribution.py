"""Per-pitcher strikeout-count DISTRIBUTION, built straight from the play-by-play.

Why this exists
---------------
parlay_sim.py projects Ks from *cluster-type* rates through a single Poisson. The
backtest said that's a foundation, not a market-beater (see [[mlb-strikeout-edge]]).
This drops the cluster abstraction and derives each pitcher's number from the only
source that tells the whole story at full resolution: pa_events_reg.csv, the
447k-row regular-season play-by-play (one row per plate appearance).

For one start the strikeout total is a sum of independent per-PA Bernoullis, each
with its own probability -> a Poisson-binomial. Without tonight's confirmed lineup
we use the pitcher's own batters-faced mix, so the honest generic is
Binomial(BF, p_blend). Drop in a real 9-man lineup and it upgrades to the true
Poisson-binomial (the DP is already here, `poisson_binomial`).

Output: ../data/exports/pitcher_k_dist.csv
  one row per qualified pitcher: projected mean Ks, the full P(>= k) ladder, and
  the FAIR decimal odds for each band (1 / P) -- i.e. the number you compare to a
  bet365/Unibet/Betano line. Their line minus our fair line = the edge to hunt.

    python pitcher_k_distribution.py
"""
from __future__ import annotations

import csv

import duckdb

SRC = "../data/exports/pa_events_reg.csv"   # verified regular-season play-by-play
OUT = "../data/exports/pitcher_k_dist.csv"

MIN_PA = 200        # pitcher needs this many faced PAs to be modelled
MIN_START_PA = 12   # a game where the pitcher faced >= this many PA counts as a start
SHRINK = 150        # empirical-Bayes strength: blend toward league hand rate
BANDS = [4, 5, 6, 7, 8, 9]  # P(K >= band); maps onto the over X.5 lines books post


def binom_ge(n: int, p: float, k: int) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    # pmf via recurrence, accumulate the tail
    pmf = (1.0 - p) ** n
    cdf_lt = pmf  # P(X = 0)
    for i in range(1, k):
        pmf *= (n - i + 1) / i * p / (1.0 - p)
        cdf_lt += pmf
    return max(0.0, 1.0 - cdf_lt)


def poisson_binomial(probs: list[float]) -> list[float]:
    """Full pmf of a sum of independent Bernoulli(probs) via DP. Ready for the
    day a confirmed lineup replaces the generic BF*p_blend assumption."""
    dist = [1.0]
    for p in probs:
        dist = [
            (dist[k] * (1 - p)) + (dist[k - 1] * p if k > 0 else 0.0)
            for k in range(len(dist) + 1)
        ]
    return dist


def main() -> None:
    con = duckdb.connect()

    # League strikeout rate per batter hand -- the shrink target.
    league = {
        row[0]: row[1]
        for row in con.execute(
            f"""SELECT stand,
                       avg(CASE WHEN events='strikeout'
                                  OR events='strikeout_double_play' THEN 1 ELSE 0 END)
                FROM read_csv_auto('{SRC}')
                GROUP BY stand"""
        ).fetchall()
    }

    # Per pitcher x batter-hand: PA and K counts.
    hand_rows = con.execute(
        f"""SELECT pitcher, player_name, stand,
                   count(*) AS pa,
                   sum(CASE WHEN events='strikeout'
                              OR events='strikeout_double_play' THEN 1 ELSE 0 END) AS k
            FROM read_csv_auto('{SRC}')
            GROUP BY pitcher, player_name, stand"""
    ).fetchall()

    # Expected batters faced per start = median PA over the pitcher's starts.
    bf_rows = con.execute(
        f"""WITH g AS (
                SELECT pitcher, game_pk, count(*) AS pa
                FROM read_csv_auto('{SRC}')
                GROUP BY pitcher, game_pk
            )
            SELECT pitcher, median(pa) AS bf, count(*) AS starts
            FROM g WHERE pa >= {MIN_START_PA}
            GROUP BY pitcher"""
    ).fetchall()
    bf = {r[0]: (r[1], r[2]) for r in bf_rows}

    # Fold the hand splits into one shrunk, faced-mix-weighted rate per pitcher.
    agg: dict[int, dict] = {}
    for pid, name, stand, pa, k in hand_rows:
        d = agg.setdefault(pid, {"name": name, "pa": 0, "k": 0, "blend_num": 0.0})
        lg = league.get(stand, 0.223)
        rate = (k + SHRINK * lg) / (pa + SHRINK)   # empirical-Bayes per hand
        d["blend_num"] += rate * pa                # weight by how often faced
        d["pa"] += pa
        d["k"] += k

    rows = []
    for pid, d in agg.items():
        if d["pa"] < MIN_PA or pid not in bf:
            continue
        p = d["blend_num"] / d["pa"]               # faced-mix-weighted K prob / PA
        n, starts = bf[pid]
        n = int(round(n))
        mean_k = n * p
        ladder = {b: binom_ge(n, p, b) for b in BANDS}
        rows.append({
            "pitcher": pid,
            "name": d["name"],
            "starts": starts,
            "bf": n,
            "k_per_pa": round(p, 4),
            "proj_mean_k": round(mean_k, 2),
            **{f"p_ge_{b}": round(ladder[b], 4) for b in BANDS},
            **{f"fair_{b}plus": (round(1 / ladder[b], 2) if ladder[b] > 1e-6 else "")
               for b in BANDS},
        })

    rows.sort(key=lambda r: r["proj_mean_k"], reverse=True)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {len(rows)} pitchers -> {OUT}")
    print(f"\nleague K/PA by hand: "
          f"L={league.get('L',0):.3f}  R={league.get('R',0):.3f}\n")
    print("top 12 by projected mean Ks per start:")
    print(f"{'pitcher':22} {'BF':>3} {'K/PA':>5} {'meanK':>6} "
          f"{'P>=6':>6} {'fair6+':>7} {'P>=8':>6}")
    for r in rows[:12]:
        print(f"{r['name'][:22]:22} {r['bf']:>3} {r['k_per_pa']:.3f} "
              f"{r['proj_mean_k']:>6} {r['p_ge_6']:>6} "
              f"{str(r['fair_6plus']):>7} {r['p_ge_8']:>6}")


if __name__ == "__main__":
    main()
