"""'Is it still live?' — re-pull current prices to confirm a logged arb before betting.

Arbs in arb_log.csv are SNAPSHOTS; lines move in seconds. Before staking real
money you must confirm BOTH legs are still priced where the log said. This hits
the live /v2/arb scan (fresh pull across ~12 books incl. Pinnacle) and reports,
per pitcher, whether the two-way best-book combo is STILL a profit (an arb) or has
MOVED into a hold.

    python arb_check.py                 # list every CURRENT arb (profit > 0)
    python arb_check.py "Yesavage"      # status of one pitcher (substring match)
    python arb_check.py "Yesavage" 500  # ... sized to a $500 bankroll

Run it RIGHT BEFORE you'd place the bet — a check from an hour ago is worthless.
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "https://strike.perfecthold.online/api/v2/arb"


def fetch(bankroll: float):
    # min_profit_pct=-25 => return even non-arb pitchers (a hold) so we can show
    # how far a moved line now sits, not just current arbs.
    url = f"{API}?bankroll={bankroll}&min_profit_pct=-25"
    return json.load(urllib.request.urlopen(url, timeout=90))


def show(o: dict) -> None:
    legs = {l["side"]: l for l in o.get("legs", [])}
    ov, un = legs.get("over", {}), legs.get("under", {})
    pct = o.get("profit_pct", 0) * 100
    live = pct > 0
    flag = f"[ARB] STILL LIVE  +{pct:.2f}%  (${o.get('guaranteed_profit',0):.2f})" if live \
        else f"[MOVED] now a {abs(pct):.2f}% hold, NOT an arb"
    print(f"\n{o['pitcher']}  --  strikeouts {o['line']}")
    print(f"  OVER  {ov.get('bookmaker',''):12} {ov.get('american',''):>+5}   "
          f"UNDER {un.get('bookmaker',''):12} {un.get('american',''):>+5}")
    print(f"  -> {flag}")
    if live:
        print(f"     stake ${ov.get('stake',0):.2f} OVER @ {ov.get('bookmaker','')}  +  "
              f"${un.get('stake',0):.2f} UNDER @ {un.get('bookmaker','')}  "
              f"(each pays ~${ov.get('payout',0):.2f})")


def main(argv) -> int:
    name = argv[0] if argv else None
    bankroll = float(argv[1]) if len(argv) > 1 else 1000.0
    d = fetch(bankroll)
    opps = d.get("opportunities", [])

    if not name:
        live = [o for o in opps if o.get("profit_pct", 0) > 0]
        print(f"CURRENT arbs (live scan): {len(live)}")
        for o in sorted(live, key=lambda x: -x.get("profit_pct", 0)):
            show(o)
        if not live:
            print("  none right now.")
        return 0

    matches = [o for o in opps if name.lower() in o.get("pitcher", "").lower()]
    if not matches:
        print(f"'{name}' not in the current slate's strikeout props "
              "(game may have started, or no prop posted now).")
        return 0
    for o in matches:
        show(o)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
