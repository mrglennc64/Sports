"""Objectives 10-12 — PAPER-ONLY parlay matrix simulator.

*** NOT BETTING ADVICE. Real money stays gated until single-leg calibration is
proven (see [[mlb-strikeout-edge]]); the backtest says the type model is a
foundation, not yet a market-beater. This builds the MACHINERY so it's ready. ***

Pipeline:
  10  project each upcoming start's strikeouts from the type model
      (pitcher-type K rate x expected batters faced, Poisson) -> P(pick side wins)
  11  rank candidate legs by edge vs the book's implied prob; keep the confident +EV
  12a number of parlays            -> all r-leg combinations of the top legs, capped
  12b legs per parlay              -> `legs_per`
  12c daily / weekly bankroll risk -> caps as a fraction of bankroll
  12d per-parlay stake             -> fractional-Kelly, capped, scaled to fit the day
  12e outcome-potential matrix     -> exact P&L distribution by enumerating every
      leg win/loss combination (handles parlays that SHARE legs / correlation)

    python parlay_sim.py
"""
from __future__ import annotations

import math
from itertools import combinations

# ---- odds + probability helpers ---------------------------------------------

def american_to_decimal(a: float) -> float:
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def implied_prob(a: float) -> float:
    return 100 / (a + 100) if a > 0 else abs(a) / (abs(a) + 100)


def pois_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def pois_sf(n: int, lam: float) -> float:
    """P(X >= n)."""
    return 1.0 - sum(pois_pmf(i, lam) for i in range(n))


def prob_side(exp_k: float, line: float, side: str) -> float:
    """Model P(pick wins) for a half-integer K line under Poisson(exp_k)."""
    over = pois_sf(math.ceil(line), exp_k)         # P(K >= ceil(line))
    return over if side == "over" else 1 - over


def full_kelly(p: float, dec: float) -> float:
    b = dec - 1
    return max(0.0, (p * b - (1 - p)) / b)


# ---- objective 10: project legs ---------------------------------------------

def project_leg(leg: dict) -> dict:
    """leg in: name, game, type, k_rate, exp_bf, line, side, odds(american)."""
    exp_k = leg["k_rate"] * leg["exp_bf"]
    p = prob_side(exp_k, leg["line"], leg["side"])
    dec = american_to_decimal(leg["odds"])
    imp = implied_prob(leg["odds"])
    return {**leg, "exp_k": exp_k, "p": p, "dec": dec, "implied": imp,
            "edge": p - imp, "kelly": full_kelly(p, dec)}


# ---- objective 11: rank confident +EV legs ----------------------------------

def rank_legs(legs: list[dict], min_edge: float) -> list[dict]:
    legs = [project_leg(l) for l in legs]
    keep = [l for l in legs if l["edge"] >= min_edge]
    return sorted(keep, key=lambda l: l["edge"], reverse=True), legs


# ---- objective 12a/b: build the parlay matrix -------------------------------

def build_parlays(legs: list[dict], legs_per: int, max_parlays: int) -> list[dict]:
    combos = []
    for combo in combinations(legs, legs_per):
        if len({l["game"] for l in combo}) < legs_per:
            continue  # never put two legs from the same game in one parlay
        p = math.prod(l["p"] for l in combo)
        dec = math.prod(l["dec"] for l in combo)
        combos.append({"legs": combo, "p": p, "dec": dec,
                       "ev": p * dec - 1, "kelly": full_kelly(p, dec)})
    combos.sort(key=lambda c: c["ev"], reverse=True)
    return combos[:max_parlays]


# ---- objective 12c/d: bankroll allocation -----------------------------------

def allocate(parlays, bankroll, daily_frac, kelly_frac, per_cap_frac):
    raw = [min(kelly_frac * c["kelly"], per_cap_frac) * bankroll for c in parlays]
    daily_cap = bankroll * daily_frac
    total = sum(raw)
    scale = daily_cap / total if total > daily_cap and total > 0 else 1.0
    for c, s in zip(parlays, raw):
        c["stake"] = round(s * scale, 2)
    return parlays, daily_cap, scale


# ---- objective 12e: exact outcome-potential matrix --------------------------

def outcome_matrix(parlays, legs):
    """Enumerate every leg win/loss combo (legs independent across games) and
    build the exact daily P&L distribution — correct even when parlays share legs."""
    leg_ids = sorted({id(l) for c in parlays for l in c["legs"]})
    idx = {lid: i for i, lid in enumerate(leg_ids)}
    leg_p = {}
    for c in parlays:
        for l in c["legs"]:
            leg_p[idx[id(l)]] = l["p"]
    L = len(leg_ids)

    dist = []  # (prob, pnl, n_parlays_won)
    for mask in range(1 << L):
        prob = 1.0
        won = [False] * L
        for i in range(L):
            hit = (mask >> i) & 1
            won[i] = bool(hit)
            prob *= leg_p[i] if hit else (1 - leg_p[i])
        pnl = 0.0
        nwon = 0
        for c in parlays:
            all_hit = all(won[idx[id(l)]] for l in c["legs"])
            if all_hit:
                pnl += c["stake"] * (c["dec"] - 1)
                nwon += 1
            else:
                pnl -= c["stake"]
        dist.append((prob, pnl, nwon))

    ev = sum(p * pnl for p, pnl, _ in dist)
    var = sum(p * (pnl - ev) ** 2 for p, pnl, _ in dist)
    p_profit = sum(p for p, pnl, _ in dist if pnl > 0)
    staked = sum(c["stake"] for c in parlays)
    best = max(dist, key=lambda t: t[1])
    worst = min(dist, key=lambda t: t[1])
    # collapse to P&L by number of parlays won
    by_n = {}
    for p, pnl, nwon in dist:
        a = by_n.setdefault(nwon, [0.0, 0.0])
        a[0] += p
        a[1] += p * pnl
    return {"ev": ev, "sd": var ** 0.5, "p_profit": p_profit, "staked": staked,
            "best": best, "worst": worst, "by_n": by_n}


# ---- demo -------------------------------------------------------------------

def main() -> None:
    BANKROLL = 1000.0
    LEGS_PER = 2          # 12b
    MAX_PARLAYS = 4       # 12a (user bankroll constraint: ~4 bets/night to start)
    DAILY_FRAC = 0.05     # 12c risk up to 5% of bankroll/day
    WEEKLY_FRAC = 0.15    # 12c
    KELLY_FRAC = 0.25     # 12d quarter-Kelly
    PER_CAP = 0.02        # 12d no single parlay risks > 2% of bankroll
    MIN_EDGE = 0.0        # keep any +EV leg for the demo
    EXP_BF = 24           # simplifying assumption (starter ~24 batters faced)

    # Objective 10 inputs: tonight's real card pitchers, real lines/odds, with the
    # TYPE-model K rate (pitcher archetype, trained on 2024-25). exp_bf assumed.
    raw = [
        {"name": "Jesus Luzardo",  "game": "MIA@PHI", "k_rate": 0.286, "line": 6.5, "side": "under", "odds": -124},
        {"name": "Reid Detmers",   "game": "LAA@ARI", "k_rate": 0.277, "line": 5.5, "side": "over",  "odds": +124},
        {"name": "Merrill Kelly",  "game": "LAA@ARI", "k_rate": 0.234, "line": 4.5, "side": "under", "odds": -119},
        {"name": "Logan Gilbert",  "game": "BAL@SEA", "k_rate": 0.234, "line": 6.5, "side": "under", "odds": +117},
        {"name": "Edward Cabrera", "game": "COL@CHC", "k_rate": 0.234, "line": 5.5, "side": "under", "odds": -112},
        {"name": "Adrian Houser",  "game": "SF@ATL",  "k_rate": 0.177, "line": 3.5, "side": "over",  "odds": -103},
        {"name": "Mitch Keller",   "game": "PIT@ATH", "k_rate": 0.199, "line": 4.5, "side": "under", "odds": -121},
    ]
    for l in raw:
        l["exp_bf"] = EXP_BF

    print("=" * 74)
    print("PAPER PARLAY SIMULATOR  (type model, illustrative — NOT betting advice)")
    print(f"bankroll ${BANKROLL:.0f} | {LEGS_PER}-leg parlays | <= {MAX_PARLAYS}/day"
          f" | daily risk {DAILY_FRAC:.0%} | quarter-Kelly | exp_bf={EXP_BF}")
    print("=" * 74)

    ranked, alllegs = rank_legs(raw, MIN_EDGE)
    print("\n[10-11] LEG PROJECTIONS (sorted by edge)")
    print(f"  {'pitcher':15}{'pick':11}{'projK':>6}{'modelP':>8}{'impl':>7}{'edge':>8}")
    for l in alllegs:
        flag = "  +EV" if l["edge"] >= MIN_EDGE and l in ranked else ""
        print(f"  {l['name']:15}{l['side'].upper()+' '+str(l['line']):11}"
              f"{l['exp_k']:6.2f}{l['p']*100:7.1f}%{l['implied']*100:6.1f}%"
              f"{l['edge']*100:+7.1f}%{flag}")

    if len(ranked) < LEGS_PER:
        print(f"\nOnly {len(ranked)} +EV legs — need {LEGS_PER} for a parlay. Stop.")
        return

    parlays = build_parlays(ranked, LEGS_PER, MAX_PARLAYS)
    parlays, daily_cap, scale = allocate(parlays, BANKROLL, DAILY_FRAC, KELLY_FRAC, PER_CAP)

    print(f"\n[12a-d] PARLAY MATRIX  (daily cap ${daily_cap:.0f}"
          f"{', scaled '+format(scale,'.2f')+'x to fit' if scale < 1 else ''})")
    print(f"  {'#':>2} {'legs':40}{'P(win)':>8}{'dec':>7}{'EV':>7}{'stake':>8}")
    for i, c in enumerate(parlays, 1):
        names = " + ".join(f"{l['name'].split()[-1]} {l['side'][0].upper()}{l['line']}"
                           for l in c["legs"])
        print(f"  {i:>2} {names:40}{c['p']*100:7.1f}%{c['dec']:7.2f}"
              f"{c['ev']*100:+6.0f}%{c['stake']:8.2f}")

    om = outcome_matrix(parlays, alllegs)
    print(f"\n[12e] OUTCOME-POTENTIAL MATRIX  (total staked ${om['staked']:.2f})")
    print(f"  expected P&L  ${om['ev']:+.2f}   st.dev ${om['sd']:.2f}"
          f"   P(profit) {om['p_profit']*100:.1f}%")
    print(f"  best case     ${om['best'][1]:+.2f}  (p={om['best'][0]*100:.1f}%)")
    print(f"  worst case    ${om['worst'][1]:+.2f}  (p={om['worst'][0]*100:.1f}%, all legs miss)")
    print(f"  {'parlays won':>12}{'probability':>14}{'E[P&L|n] contrib':>18}")
    for nwon in sorted(om["by_n"]):
        prob, contrib = om["by_n"][nwon]
        print(f"  {nwon:>12}{prob*100:13.1f}%{contrib:+17.2f}")
    print("\n(weekly cap would track cumulative daily stakes vs "
          f"{WEEKLY_FRAC:.0%} of bankroll; paper-trade these before any real stake.)")


if __name__ == "__main__":
    main()
