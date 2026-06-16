"""Export the type-model priors the backend needs to apply the synthesis live.

The synthesis (synthesis_backtest.py) proved that regressing a pitcher's K rate
toward his ARCHETYPE — heavily, by sample size — generalizes better than his own
history, and the type matchup is the best base. The backend already carries the
opponent K% (its opponent factor), so to wire the synthesis in it only needs, per
pitcher: his archetype and that archetype's marginal K rate, plus the league rate.

Writes a small JSON the backend loads (no DuckDB dependency in the deployed app):
    backend/app/data/type_priors.json
    { "league_k": float, "bf_per_start": float,
      "pmarg": {ptype: per-PA K rate},          # 2024-25 train
      "pitcher_type": {player_id: ptype} }       # latest season available

    python export_priors.py
"""
from __future__ import annotations

import json

import duckdb

DB = "../data/baseball.duckdb"
OUT = "../backend/app/data/type_priors.json"
TRAIN = (2024, 2025)


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    # pitcher-type marginal per-PA K rate + league rate (2024-25 regular season)
    rows = con.execute(f"""
        SELECT pit.cluster_v2 AS p, count(*) n,
               count(*) FILTER (WHERE e.events LIKE 'strikeout%') k
        FROM pa_events_reg e
        JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
        WHERE e.season IN {TRAIN} AND pit.cluster_v2 IS NOT NULL
        GROUP BY 1
    """).fetchall()
    pmarg = {str(p): k / n for p, n, k in rows}
    tot_n = sum(n for _, n, _ in rows)
    tot_k = sum(k for _, _, k in rows)
    league_k = tot_k / tot_n

    # each pitcher's archetype, preferring the most recent season's assignment
    pt: dict[str, int] = {}
    for season in (2024, 2025, 2026):  # later seasons overwrite -> latest wins
        for pid, cl in con.execute(
            "SELECT player_id, cluster_v2 FROM pitchers "
            "WHERE season=? AND cluster_v2 IS NOT NULL", [season]
        ).fetchall():
            pt[str(pid)] = int(cl)
    con.close()

    priors = {
        "league_k": round(league_k, 5),
        "bf_per_start": 24.0,
        "pmarg": {k: round(v, 5) for k, v in pmarg.items()},
        "pitcher_type": pt,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(priors, f, indent=0, sort_keys=True)
    print(f"wrote {OUT}: league_k={league_k:.3f}, "
          f"{len(pmarg)} types, {len(pt)} pitchers typed")
    for t in sorted(pmarg, key=lambda x: pmarg[x]):
        print(f"  type {t}: pmarg K% {pmarg[t]*100:.1f}")


if __name__ == "__main__":
    main()
