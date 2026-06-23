"""Edge flagger: our play-by-play K distribution vs the posted sportsbook line.

The missing half of pitcher_k_distribution.py. That script produces our FAIR
probability for each strikeout band, straight from the 447k-row play-by-play. This
one ingests the book's posted line + two-sided odds, de-vigs it to the market's
fair probability, and flags where OUR number disagrees with THEIRS. That gap, not
the projection itself, is the edge.

Deliberately separate from the deployed v2 engine: that one prices off the
cluster/ensemble projection (the EXP.KS column on the live page), the one the
backtest flagged as overconfident in the >15% bucket. This prices off the
pitcher's own play-by-play rate. Same de-vig/Kelly math as backend edge.py,
inlined per the analytics-dir convention (cf. parlay_sim.py).

Line -> band: books post half-lines, so over X.5 == P(K >= ceil(X.5)) == our
p_ge_{ceil} column exactly. Under = 1 - over.

    python edge_flagger.py [lines.csv] [bankroll]
        lines.csv : date,pitcher,line,over_odds,under_odds  (default ../data/lines.csv)
                    blank odds on a side = that side not offered.

NOT betting advice. Edges are unproven until logged CLV says they beat the close.
"""
from __future__ import annotations

import csv
import math
import sys

DIST = "../data/exports/pitcher_k_dist.csv"
KELLY_FRACTION = 0.25   # quarter-Kelly
KELLY_CAP = 0.05        # never more than 5% of bankroll on one leg
MIN_EDGE = 0.03         # flag at >= 3 pts of edge
MAX_EDGE = 0.20         # drop implausible >20% edges (overconfidence, per backtest)

# ---- odds helpers (mirror backend/app/model/edge.py) ------------------------

def implied_prob(american: float) -> float:
    return 100 / (american + 100) if american > 0 else abs(american) / (abs(american) + 100)


def american_to_decimal(american: float) -> float:
    return 1 + american / 100 if american > 0 else 1 + 100 / abs(american)


def devig_two_way(over_odds, under_odds):
    """Proportional (multiplicative) de-vig. Returns (fair_over, fair_under)."""
    ro, ru = implied_prob(over_odds), implied_prob(under_odds)
    s = ro + ru
    return ro / s, ru / s


def safe_kelly(prob: float, american: float) -> float:
    b = american_to_decimal(american) - 1.0
    if b <= 0:
        return 0.0
    full = (b * prob - (1 - prob)) / b
    return min(full * KELLY_FRACTION, KELLY_CAP) if full > 0 else 0.0


def norm_name(n: str) -> str:
    """'Sale, Chris' and 'Chris Sale' -> 'chris sale'."""
    n = n.strip().strip('"')
    if "," in n:
        last, first = (p.strip() for p in n.split(",", 1))
        n = f"{first} {last}"
    return " ".join(n.lower().split())


# ---- main -------------------------------------------------------------------

def main() -> None:
    lines_path = sys.argv[1] if len(sys.argv) > 1 else "../data/lines.csv"
    bankroll = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0

    # Our fair probabilities, keyed by normalised pitcher name.
    dist = {}
    with open(DIST, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dist[norm_name(row["name"])] = row
            dist[str(row["pitcher"])] = row   # also key by MLB id (cron-captured rows)

    flagged, no_model, no_devig = [], [], 0
    with open(lines_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            raw = (r.get("pitcher") or r.get("player") or "").strip()
            d = dist.get(raw) or dist.get(norm_name(raw))   # try MLB id, then name
            if d is None:
                no_model.append(raw)
                continue
            line = float(r["line"])
            band = math.ceil(line)
            col = f"p_ge_{band}"
            if col not in d or d[col] == "":
                no_model.append(f"{raw} (line {line} out of band)")
                continue
            p_over = float(d[col])
            p_under = 1.0 - p_over

            oo = r.get("over_odds", "").strip()
            uo = r.get("under_odds", "").strip()
            if oo and uo:
                fair_over, fair_under = devig_two_way(float(oo), float(uo))
            elif oo:                       # one-sided: use raw implied as fair
                fair_over, fair_under, uo = implied_prob(float(oo)), 1 - implied_prob(float(oo)), None
                no_devig += 1
            elif uo:
                fair_under = implied_prob(float(uo)); fair_over = 1 - fair_under; oo = None
                no_devig += 1
            else:
                continue

            over_edge = p_over - fair_over
            under_edge = p_under - fair_under
            if over_edge >= under_edge:
                side, p, fair, odds, ed = "OVER", p_over, fair_over, oo, over_edge
            else:
                side, p, fair, odds, ed = "UNDER", p_under, fair_under, uo, under_edge

            kelly = safe_kelly(p, float(odds)) if odds else 0.0
            flagged.append({
                "pitcher": raw, "date": r.get("date", ""),
                "line": line, "side": side, "exp_k": d["proj_mean_k"],
                "model": p, "fair": fair, "odds": odds, "edge": ed,
                "kelly": kelly, "stake": round(kelly * bankroll, 2),
            })

    flagged.sort(key=lambda x: x["edge"], reverse=True)
    card = [x for x in flagged if MIN_EDGE <= x["edge"] <= MAX_EDGE]

    print(f"\n  lines: {lines_path}   bankroll: ${bankroll:.0f}")
    print(f"  {len(flagged)} priced  |  {len(card)} flagged "
          f"(edge {MIN_EDGE:.0%}-{MAX_EDGE:.0%})  |  "
          f"{len(no_model)} no model  |  {no_devig} one-sided (raw implied)\n")
    print(f"  {'PITCHER':20} {'LINE':>4} {'PICK':5} {'EXP':>4} "
          f"{'MODEL':>6} {'FAIR':>6} {'ODDS':>6} {'EDGE':>6} {'KELLY':>6} {'STAKE':>7}")
    for x in card:
        print(f"  {x['pitcher'][:20]:20} {x['line']:>4} {x['side']:5} "
              f"{str(x['exp_k']):>4} {x['model']:>6.1%} {x['fair']:>6.1%} "
              f"{str(x['odds']):>6} {x['edge']:>+6.1%} {x['kelly']:>6.1%} "
              f"${x['stake']:>6.2f}")
    if no_model:
        print(f"\n  no model for: {', '.join(sorted(set(no_model))[:12])}"
              + (" ..." if len(set(no_model)) > 12 else ""))


if __name__ == "__main__":
    main()
