"""Run TONIGHT's live card through the paper parlay simulator (objs 11-12).

Pulls the live engine's slate (the ensemble's own model probabilities + book
odds), takes the card legs, and runs the same build->allocate->outcome-matrix
machinery from parlay_sim. PAPER ONLY — the ensemble probs are uncalibrated
(it over-projects), so EV here is illustrative, not an edge claim.

    python parlay_today.py
"""
from __future__ import annotations

import json
import urllib.request

from parlay_sim import (
    allocate, american_to_decimal, build_parlays, full_kelly, implied_prob,
    outcome_matrix,
)

SLATE = "https://strike.perfecthold.online/api/v2/slate"
BANKROLL, LEGS_PER, MAX_PARLAYS = 1000.0, 2, 4
DAILY_FRAC, KELLY_FRAC, PER_CAP = 0.05, 0.25, 0.02


def main() -> None:
    d = json.load(urllib.request.urlopen(SLATE, timeout=60))
    card = d.get("card") or []
    print(f"{SLATE.split('//')[1].split('/')[0]}  date {d.get('date')}  "
          f"card_size {d.get('card_size')}\n")

    legs = []
    for r in card:
        side = r["side"]
        odds = r.get("over_odds") if side == "over" else r.get("under_odds")
        if odds is None:
            continue
        p = r.get("model_prob")
        dec = american_to_decimal(odds)
        legs.append({
            "name": r["pitcher"], "game": r.get("game_pk", r["pitcher"]),
            "side": side, "line": r["line"], "odds": odds,
            "p": p, "dec": dec, "implied": implied_prob(odds),
            "edge": p - implied_prob(odds), "kelly": full_kelly(p, dec),
        })

    print("CARD LEGS (live ensemble probabilities):")
    print(f"  {'pitcher':16}{'pick':11}{'modelP':>8}{'impl':>7}{'edge':>8}{'odds':>7}")
    for l in legs:
        print(f"  {l['name']:16}{l['side'].upper()+' '+str(l['line']):11}"
              f"{l['p']*100:7.1f}%{l['implied']*100:6.1f}%{l['edge']*100:+7.1f}%"
              f"{l['odds']:>7}")

    if len(legs) < LEGS_PER:
        print("\nnot enough card legs for a parlay")
        return

    parlays = build_parlays(legs, LEGS_PER, MAX_PARLAYS)
    parlays, daily_cap, scale = allocate(parlays, BANKROLL, DAILY_FRAC, KELLY_FRAC, PER_CAP)

    print(f"\n[12a-d] PARLAY MATRIX  (bankroll ${BANKROLL:.0f}, {LEGS_PER}-leg, "
          f"<= {MAX_PARLAYS}/day, daily cap ${daily_cap:.0f}"
          f"{', scaled '+format(scale,'.2f')+'x' if scale < 1 else ''})")
    print(f"  {'#':>2} {'legs':38}{'P(win)':>8}{'dec':>7}{'EV':>7}{'stake':>8}")
    for i, c in enumerate(parlays, 1):
        names = " + ".join(f"{l['name'].split()[-1]} {l['side'][0].upper()}{l['line']}"
                           for l in c["legs"])
        print(f"  {i:>2} {names:38}{c['p']*100:7.1f}%{c['dec']:7.2f}"
              f"{c['ev']*100:+6.0f}%{c['stake']:8.2f}")

    om = outcome_matrix(parlays, legs)
    print(f"\n[12e] OUTCOME-POTENTIAL MATRIX  (staked ${om['staked']:.2f})")
    print(f"  expected P&L  ${om['ev']:+.2f}   st.dev ${om['sd']:.2f}"
          f"   P(profit) {om['p_profit']*100:.1f}%")
    print(f"  best  ${om['best'][1]:+.2f} (p={om['best'][0]*100:.1f}%)"
          f"   worst ${om['worst'][1]:+.2f} (p={om['worst'][0]*100:.1f}%)")
    print(f"  {'parlays won':>12}{'probability':>14}{'E[P&L] contrib':>16}")
    for nwon in sorted(om["by_n"]):
        prob, contrib = om["by_n"][nwon]
        print(f"  {nwon:>12}{prob*100:13.1f}%{contrib:+15.2f}")
    print("\nPAPER ONLY — ensemble probs are uncalibrated (over-projects); "
          "EV is illustrative, not an edge claim.")


if __name__ == "__main__":
    main()
