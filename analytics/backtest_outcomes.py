"""Objective 8-9, multi-outcome — does the type matchup predict OTHER pitcher props
(walks, home runs, hits allowed), not just strikeouts? Those extra outcomes are the
whole point of the type matrix: more bettable leg types for the eventual parlays.

Same honest split as backtest_matchup.py: train cell rates on 2024+2025, test on
2026 starts by summing a per-PA probability over the ACTUAL batters faced, vs the
real per-start count. For each outcome, three nested models (league / pitcher-type /
matchup, EB-shrunk) — the question each time is whether matchup beats pitcher-type.

    python backtest_outcomes.py
"""
from __future__ import annotations

from collections import defaultdict

import duckdb

DB = "../data/baseball.duckdb"
TRAIN = (2024, 2025)
TEST = 2026
SHRINK = 200.0
MIN_BF = 12

# outcome -> (python predicate on events, SQL FILTER predicate)
OUTCOMES = {
    "K":   (lambda e: e.startswith("strikeout"),
            "events LIKE 'strikeout%'"),
    "BB":  (lambda e: e in ("walk", "intent_walk"),
            "events IN ('walk','intent_walk')"),
    "HR":  (lambda e: e == "home_run",
            "events = 'home_run'"),
    "HIT": (lambda e: e in ("single", "double", "triple", "home_run"),
            "events IN ('single','double','triple','home_run')"),
}


def main() -> None:
    con = duckdb.connect(DB)
    filt = ",\n".join(
        f"count(*) FILTER (WHERE {sql}) AS {oc.lower()}"
        for oc, (_py, sql) in OUTCOMES.items()
    )
    tr = con.execute(f"""
        SELECT pit.cluster_v2 AS p, bat.cluster_v2 AS b, count(*) AS n_pa,
               {filt}
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
        WHERE e.season IN {TRAIN}
        GROUP BY 1,2
    """).fetchall()

    ocs = list(OUTCOMES)
    cell_n = {}
    cell_cnt = {oc: {} for oc in ocs}
    pmarg_n = defaultdict(int)
    pmarg_cnt = {oc: defaultdict(int) for oc in ocs}
    tot_n = 0
    tot_cnt = {oc: 0 for oc in ocs}
    for row in tr:
        p, b, n_pa = row[0], row[1], row[2]
        if p is None or b is None:
            continue
        counts = dict(zip(ocs, row[3:]))
        cell_n[(p, b)] = n_pa
        pmarg_n[p] += n_pa
        tot_n += n_pa
        for oc in ocs:
            cell_cnt[oc][(p, b)] = counts[oc]
            pmarg_cnt[oc][p] += counts[oc]
            tot_cnt[oc] += counts[oc]
    league = {oc: tot_cnt[oc] / tot_n for oc in ocs}
    pmarg = {oc: {p: pmarg_cnt[oc][p] / pmarg_n[p] for p in pmarg_n} for oc in ocs}

    def cell_rate(oc, p, b):
        if p is None:
            return league[oc]
        prior = pmarg[oc].get(p, league[oc])
        if b is None or (p, b) not in cell_n:
            return prior
        n, c = cell_n[(p, b)], cell_cnt[oc][(p, b)]
        return (c + SHRINK * prior) / (n + SHRINK)

    rows = con.execute(f"""
        SELECT e.game_pk, e.pitcher, pit.cluster_v2 AS p, bat.cluster_v2 AS b, e.events
        FROM pa_events_reg e
        LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season={TEST}
        LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season={TEST}
        WHERE e.season={TEST}
    """).fetchall()
    con.close()

    def new_start():
        d = {"bf": 0}
        for oc in ocs:
            d[oc + "_a"] = 0
            d[oc + "_L"] = 0.0
            d[oc + "_P"] = 0.0
            d[oc + "_M"] = 0.0
        return d

    starts = defaultdict(new_start)
    for gpk, pid, p, b, events in rows:
        s = starts[(gpk, pid)]
        s["bf"] += 1
        for oc, (py, _sql) in OUTCOMES.items():
            s[oc + "_a"] += 1 if (events and py(events)) else 0
            s[oc + "_L"] += league[oc]
            s[oc + "_P"] += pmarg[oc].get(p, league[oc])
            s[oc + "_M"] += cell_rate(oc, p, b)

    sel = [s for s in starts.values() if s["bf"] >= MIN_BF]
    n = len(sel)

    def metrics(oc, mk):
        px = [s[oc + "_" + mk] for s in sel]
        ax = [s[oc + "_a"] for s in sel]
        mae = sum(abs(px[i] - ax[i]) for i in range(n)) / n
        mpx, max_ = sum(px) / n, sum(ax) / n
        cov = sum((px[i] - mpx) * (ax[i] - max_) for i in range(n))
        vp = sum((v - mpx) ** 2 for v in px) ** 0.5
        va = sum((v - max_) ** 2 for v in ax) ** 0.5
        return mae, (cov / (vp * va) if vp and va else 0.0)

    print(f"Train {TRAIN} -> Test {TEST}.  held-out starts: {n}  (min_bf={MIN_BF})\n")
    print(f"{'OUTCOME':8}{'per-start':>10}  "
          f"{'league MAE':>11}{'pType MAE':>11}{'match MAE':>11}{'  match corr':>12}"
          f"{'  lineup gain':>13}")
    print("-" * 78)
    for oc in ocs:
        avg = sum(s[oc + "_a"] for s in sel) / n
        Lm = metrics(oc, "L")[0]
        Pm = metrics(oc, "P")[0]
        Mm, Mc = metrics(oc, "M")
        gain = 100 * (Pm - Mm) / Pm if Pm else 0.0
        print(f"{oc:8}{avg:10.2f}  {Lm:11.3f}{Pm:11.3f}{Mm:11.3f}{Mc:12.3f}"
              f"{gain:+12.1f}%")
    print("\n(lineup gain = matchup MAE improvement over pitcher-type-only; "
          ">0 means opponent-lineup typing helps)")


if __name__ == "__main__":
    main()
