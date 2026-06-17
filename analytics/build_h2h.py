"""Objective — pitcher-vs-batter (head-to-head) K rate, honestly regressed.

The seductive but dangerous idea: "pitcher X owns batter Y, he's struck him out
4 of 6 times". Almost every specific (pitcher, batter) pair has a tiny sample
(2-3 PAs), so its raw K rate is pure noise. The statistically honest move is
empirical-Bayes shrinkage toward a robust prior — here the pooled
pitcher-TYPE x batter-TYPE K rate (`matchup_outcomes`) for that pair's archetypes:

    h2h_k_shrunk = (n_k + SHRINK * prior_rate) / (n_pa + SHRINK)

With SHRINK heavy, the rare pair that DOES have real history (20+ PAs) gets a
small nudge off the type rate, while the typical 2-3 PA pair safely collapses
back onto the type rate. We then measure how little H2H actually moves the number
versus the type-matchup base — the expectation (and the honest finding) is that
it is ~negligible, which is exactly why per-matchup history should not be trusted.

Writes table `h2h_matchup`; prints a report quantifying the (small) movement.

    python build_h2h.py
"""
from __future__ import annotations

import duckdb

DB = "../data/baseball.duckdb"

# Heavy shrink toward the type-matchup prior. SHRINK is the pseudo-count of prior
# PAs: at n_pa=SHRINK the pair's own data and the prior get equal weight. 1600 is
# the value synthesis_backtest.py's K-sweep found optimal for the analogous
# pitcher-individual-vs-type shrink (best synthesis K=1600), so we reuse it here.
# At 1600, a 20-PA pair keeps only 20/1620 ~= 1.2% of its own signal — by design.
SHRINK = 1600.0


def main() -> None:
    con = duckdb.connect(DB)

    # Global league K rate — last-resort fallback when a pair has no usable
    # cluster/prior at all (e.g. a player missing a cluster_v2 label).
    league_k = con.execute("""
        SELECT count(*) FILTER (WHERE events LIKE 'strikeout%')::DOUBLE / count(*)
        FROM pa_events_reg
    """).fetchone()[0]

    # Build h2h_matchup in one statement.
    #
    # pair_season: per (pitcher, batter, season) counts, carrying that season's
    #   OWN cluster labels (each PA joins to its own season's player rows).
    # pair: collapse seasons -> total n_pa/n_k per pair, and pick the pair's
    #   pcluster/bcluster from the LATEST season in which the pair met (documented
    #   tie-break: most recent shared season wins; clusters can drift season to
    #   season and the latest label is the most current archetype read).
    # Then join the pooled type-vs-type cell for the prior, shrink, and fall back
    #   to the prior, then to the league rate, when the prior is missing.
    con.execute(f"""
        CREATE OR REPLACE TABLE h2h_matchup AS
        WITH pair_season AS (
          SELECT e.pitcher, e.batter, e.season,
                 pit.cluster_v2 AS p_cl, bat.cluster_v2 AS b_cl,
                 count(*) AS n_pa,
                 count(*) FILTER (WHERE e.events LIKE 'strikeout%') AS n_k
          FROM pa_events_reg e
          LEFT JOIN pitchers pit ON pit.player_id=e.pitcher AND pit.season=e.season
          LEFT JOIN batters  bat ON bat.player_id=e.batter  AND bat.season=e.season
          GROUP BY 1,2,3,4,5
        ),
        latest AS (
          -- the pair's clusters as of the most recent season they faced off
          SELECT pitcher, batter,
                 arg_max(p_cl, season) AS pcluster,
                 arg_max(b_cl, season) AS bcluster
          FROM pair_season
          GROUP BY 1,2
        ),
        pair AS (
          SELECT ps.pitcher, ps.batter,
                 sum(ps.n_pa) AS n_pa, sum(ps.n_k) AS n_k,
                 l.pcluster, l.bcluster
          FROM pair_season ps
          JOIN latest l ON l.pitcher=ps.pitcher AND l.batter=ps.batter
          GROUP BY 1,2,5,6
        )
        SELECT p.pitcher, p.batter, p.n_pa, p.n_k,
               p.pcluster, p.bcluster,
               -- PRIOR: the type-vs-type K rate for this pair's archetypes.
               CASE WHEN m.n_pa > 0 THEN m.n_k::DOUBLE / m.n_pa END AS prior_k,
               -- empirical-Bayes shrink toward the prior; if no prior, use league
               CASE
                 WHEN m.n_pa > 0 THEN
                   (p.n_k + {SHRINK} * (m.n_k::DOUBLE / m.n_pa))
                   / (p.n_pa + {SHRINK})
                 ELSE
                   (p.n_k + {SHRINK} * {league_k})
                   / (p.n_pa + {SHRINK})
               END AS h2h_k_shrunk
        FROM pair p
        LEFT JOIN matchup_outcomes m
               ON m.pitcher_cluster = p.pcluster
              AND m.batter_cluster  = p.bcluster
    """)

    # ---- report -------------------------------------------------------------
    total = con.execute("SELECT count(*) FROM h2h_matchup").fetchone()[0]
    print(f"h2h_matchup: {total} (pitcher,batter) pairs   "
          f"SHRINK={SHRINK:.0f}   league K%={league_k:.1%}\n")

    print("pairs by n_pa bucket:")
    buckets = con.execute("""
        SELECT CASE
                 WHEN n_pa = 1 THEN '1'
                 WHEN n_pa BETWEEN 2 AND 4 THEN '2-4'
                 WHEN n_pa BETWEEN 5 AND 9 THEN '5-9'
                 WHEN n_pa BETWEEN 10 AND 19 THEN '10-19'
                 ELSE '20+'
               END AS bucket,
               count(*) AS pairs,
               min(n_pa) AS lo
        FROM h2h_matchup GROUP BY 1 ORDER BY lo
    """).fetchall()
    for bucket, pairs, _ in buckets:
        print(f"  {bucket:>5}: {pairs:>8} pairs  ({pairs/total:.1%})")

    # mean |shrunk - prior|: how far H2H moves the number off the type base.
    # Restrict to pairs that actually have a prior (a cluster cell) so the diff
    # is apples-to-apples; pairs without a prior have nothing to move off of.
    overall = con.execute("""
        SELECT avg(abs(h2h_k_shrunk - prior_k))
        FROM h2h_matchup WHERE prior_k IS NOT NULL
    """).fetchone()[0]
    big = con.execute("""
        SELECT avg(abs(h2h_k_shrunk - prior_k))
        FROM h2h_matchup WHERE prior_k IS NOT NULL AND n_pa >= 20
    """).fetchone()[0]
    print(f"\nmean |h2h_k_shrunk - prior_k|  overall : {overall:.5f}")
    print(f"mean |h2h_k_shrunk - prior_k|  n_pa>=20: "
          f"{big if big is not None else float('nan'):.5f}")
    print("  (tiny overall, slightly larger for 20+ -> H2H barely moves the base)")

    print("\ntop 5 pairs by |h2h_k_shrunk - prior_k| (where history moves it most):")
    print(f"  {'pitcher':>9} {'batter':>9} {'n_pa':>5} {'n_k':>4} "
          f"{'prior_k':>8} {'shrunk':>8} {'delta':>8}")
    top = con.execute("""
        SELECT pitcher, batter, n_pa, n_k, prior_k, h2h_k_shrunk,
               abs(h2h_k_shrunk - prior_k) AS d
        FROM h2h_matchup WHERE prior_k IS NOT NULL
        ORDER BY d DESC LIMIT 5
    """).fetchall()
    for pit, bat, n_pa, n_k, prior, shrunk, d in top:
        print(f"  {pit:>9} {bat:>9} {n_pa:>5} {n_k:>4} "
              f"{prior:>8.4f} {shrunk:>8.4f} {shrunk-prior:>+8.4f}")

    con.close()


if __name__ == "__main__":
    main()
