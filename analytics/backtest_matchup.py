"""Objectives 8-9 — predict pitcher strikeouts from the type matrix, then backtest
it OUT-OF-SAMPLE and test whether opponent-lineup typing actually adds value.

Honest split: the matchup rates are TRAINED on 2024+2025 and TESTED on 2026 starts
(2026 PAs never enter training). For each 2026 start we sum a per-PA strikeout
probability over the ACTUAL batters faced (so we isolate matchup-rate quality from
the separate problem of projecting how many batters a pitcher faces) and compare to
the real strikeout total.

Three nested models, to see what each layer of information buys:
  1. league      — every PA = league K% (no pitcher, no batter info)
  2. pitcher-type— the pitcher archetype's overall K% (ignores the lineup)
  3. matchup     — pitcher-type x batter-type cell, empirical-Bayes shrunk toward
                   the pitcher-type marginal so thin cells don't over-speak
If (3) beats (2) on held-out starts, knowing the opponent lineup's TYPES helps.

Caveat: 2026 player TYPES are assigned from 2026-season stats, a mild same-season
leak on the labels (not the rates). A stricter pass would type 2026 players from
prior years; flagged for later.

    python backtest_matchup.py
"""
from __future__ import annotations

from collections import defaultdict

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
SHRINK = 200.0      # empirical-Bayes strength (PAs) toward the pitcher-type prior
MIN_BF = 12         # a "start" = faced >= this many batters (drops relief cameos)


def _is_k(events: str) -> int:
    return 1 if events and events.startswith("strikeout") else 0


def main() -> None:
    con = duckdb.connect(DB)

    # ---- TRAIN rates from 2024+2025 ------------------------------------------
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
    league = tot_k / tot_n
    pmarg = {p: pmarg_k[p] / pmarg_n[p] for p in pmarg_n}

    # individual-pitcher K rate (2024-25), EB-shrunk toward his type marginal —
    # a reference ceiling for "pitcher-only" info vs the coarse type abstraction.
    pind_rows = con.execute(f"""
        SELECT e.pitcher, pit.cluster_v2 AS p, count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        WHERE e.season IN {TRAIN}
        GROUP BY 1,2
    """).fetchall()
    pind = {}
    for pid, p, n, k in pind_rows:
        prior = pmarg.get(p, league)
        pind[pid] = (k + SHRINK * prior) / (n + SHRINK)

    def cell_rate(p, b):
        """EB-shrunk pitcher-type x batter-type K rate; falls back gracefully."""
        if p is None:
            return league
        prior = pmarg.get(p, league)
        if b is None or (p, b) not in cell_n:
            return prior
        n, k = cell_n[(p, b)], cell_k[(p, b)]
        return (k + SHRINK * prior) / (n + SHRINK)

    # ---- TEST on 2026 starts -------------------------------------------------
    rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, pit.cluster_v2 AS p, bat.cluster_v2 AS b, e.events
        FROM pa_events_reg e
        LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season={TEST}
        LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season={TEST}
        WHERE e.season={TEST}
        ORDER BY e.game_pk, e.pitcher
    """).fetchall()
    con.close()

    starts = defaultdict(lambda: {"bf": 0, "actual": 0, "league": 0.0,
                                  "ptype": 0.0, "pind": 0.0, "matchup": 0.0})
    for gpk, pid, p, b, events in rows:
        s = starts[(gpk, pid)]
        s["bf"] += 1
        s["actual"] += _is_k(events)
        s["league"] += league
        s["ptype"] += pmarg.get(p, league)
        s["pind"] += pind.get(pid, pmarg.get(p, league))
        s["matchup"] += cell_rate(p, b)

    sel = [s for s in starts.values() if s["bf"] >= MIN_BF]
    n = len(sel)

    def metrics(key):
        ae = [abs(s[key] - s["actual"]) for s in sel]
        bias = sum(s[key] - s["actual"] for s in sel) / n
        # correlation of predicted vs actual
        px = [s[key] for s in sel]; ax = [s["actual"] for s in sel]
        mpx = sum(px) / n; max_ = sum(ax) / n
        cov = sum((px[i]-mpx)*(ax[i]-max_) for i in range(n))
        vp = sum((v-mpx)**2 for v in px) ** 0.5
        va = sum((v-max_)**2 for v in ax) ** 0.5
        r = cov / (vp*va) if vp and va else 0.0
        return sum(ae)/n, bias, r

    print(f"Train {TRAIN} -> Test {TEST}.  league K%={league:.3f}  "
          f"shrink={SHRINK:.0f}  min_bf={MIN_BF}")
    print(f"held-out starts graded: {n}\n")
    print(f"{'MODEL':14}{'MAE':>7}{'BIAS':>8}{'CORR':>7}")
    print("-" * 36)
    for key, name in (("league", "league"), ("ptype", "pitcher-type"),
                      ("pind", "pitcher-indiv"), ("matchup", "matchup (type)")):
        mae, bias, r = metrics(key)
        print(f"{name:14}{mae:7.3f}{bias:+8.3f}{r:7.3f}")

    mae_p = metrics("ptype")[0]
    mae_m = metrics("matchup")[0]
    mae_i = metrics("pind")[0]
    print(f"\nmatchup vs pitcher-type : MAE {mae_p-mae_m:+.4f} "
          f"({100*(mae_p-mae_m)/mae_p:+.1f}%) -> lineup-type signal")
    print(f"indiv  vs pitcher-type : MAE {mae_p-mae_i:+.4f} "
          f"({100*(mae_p-mae_i)/mae_p:+.1f}%) -> individual-vs-type signal")


if __name__ == "__main__":
    main()
