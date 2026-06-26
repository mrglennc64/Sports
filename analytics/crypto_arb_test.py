"""Cross-venue arb test: Stake (manual) vs your existing 12-book scanner.

Paste today's Stake lines below, then run:

    python crypto_arb_test.py

It pulls your live VPS arb scan (12 books incl. Pinnacle), mixes in the
Stake quotes, and reports if ANY combination creates a locked arb.

============================= STAKE LINES — PASTE BELOW =============================

Format: pitcher_name, line, over_decimal, under_decimal

Example:
    Ian Seymour, 5.5, 1.85, 1.82
    Casey Legumina, 1.5, 2.31, 1.52
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

# -- Stake lines — paste today's here ------------------------------------------
STAKE_RAW = """\
Ian Seymour, 5.5, 1.85, 1.82
Casey Legumina, 1.5, 2.31, 1.52
Bubba Chandler, 4.5, 1.75, 1.93
Landen Roupp, 5.5, 1.63, 2.10
Jeffrey Springs, 4.5, 1.93, 1.75
Tatsuya Imai, 5.5, 2.10, 1.63
Cristopher Sanchez, 6.5, 1.92, 1.76
Kevin Gausman, 5.5, 1.61, 2.13
MacKenzie Gore, 4.5, 1.64, 2.08
Cam Schlittler, 6.5, 2.06, 1.66
Freddy Peralta, 5.5, 2.09, 1.64
Matthew Boyd, 4.5, 1.78, 1.89
Michael McGreevy, 2.5, 1.52, 2.32
Zac Gallen, 3.5, 1.67, 2.04
"""


# -- Data types & math ---------------------------------------------------------

@dataclass
class Quote:
    bookmaker: str
    line: float
    over_odds: float   # american
    under_odds: float  # american


def american_to_decimal(american: float) -> float:
    """American odds (e.g. -110) → decimal (1.909)."""
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 - 100.0 / american


def decimal_to_american(decimal: float) -> float:
    """Decimal odds (e.g. 1.85) → american (-118)."""
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100)
    return round(-100.0 / (decimal - 1.0))


def two_way_arb_value(dec_over: float, dec_under: float) -> float:
    """Sum of inverse decimal odds. < 1.0 = locked profit."""
    return 1.0 / dec_over + 1.0 / dec_under


def split_stakes(bankroll: float, dec_over: float, dec_under: float
                 ) -> tuple[float, float]:
    """Stakes that equalise payout on both sides."""
    inv_o, inv_u = 1.0 / dec_over, 1.0 / dec_under
    total = inv_o + inv_u
    return bankroll * inv_o / total, bankroll * inv_u / total


# -- Scanner -------------------------------------------------------------------

def scan_pitcher(pitcher: str, quotes: list[Quote], bankroll: float = 1000.0
                 ) -> None:
    """Print any arb for one pitcher, flagging cross-venue (Stake) combos."""
    # Group quotes by line — arb only exists within the SAME line
    by_line: dict[float, list[Quote]] = {}
    for q in quotes:
        by_line.setdefault(q.line, []).append(q)

    for line, qs in by_line.items():
        best_over = max(qs, key=lambda q: american_to_decimal(q.over_odds))
        best_under = max(qs, key=lambda q: american_to_decimal(q.under_odds))

        dec_o = american_to_decimal(best_over.over_odds)
        dec_u = american_to_decimal(best_under.under_odds)
        arb_val = two_way_arb_value(dec_o, dec_u)

        if arb_val >= 1.0:
            continue  # no arb here

        profit_pct = (1.0 - arb_val) / arb_val
        stake_o, stake_u = split_stakes(bankroll, dec_o, dec_u)
        payout = stake_o * dec_o
        has_stake = best_over.bookmaker == "stake" or best_under.bookmaker == "stake"
        cross = best_over.bookmaker != best_under.bookmaker

        print(f"\n{'!! STAKE ARB' if has_stake else '  internal'} — {pitcher}  line {line}")
        print(f"   OVER  {best_over.bookmaker:16} {best_over.over_odds:+.0f}  -> {dec_o:.3f}")
        print(f"   UNDER {best_under.bookmaker:16} {best_under.under_odds:+.0f}  -> {dec_u:.3f}")
        print(f"   Arb value: {arb_val:.4f}   Profit: +{profit_pct:.2%}   "
              f"Guaranteed: ${payout - bankroll:.2f} on ${bankroll:.0f}")
        if cross:
            print(f"   Stake ${stake_o:.0f} OVER @ {best_over.bookmaker}  +  "
                  f"${stake_u:.0f} UNDER @ {best_under.bookmaker}")
        else:
            print(f"   [SAME-BOOK] ({best_over.bookmaker}) - pricing error? Skip.")


# -- Main ----------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("CRYPTO ARB TEST: Stake (manual) vs VPS (12-book live scan)")
    print("=" * 70)

    raw = STAKE_RAW.strip()
    if not raw:
        print("\nNo Stake lines pasted. Edit crypto_arb_test.py and fill in STAKE_RAW.\n")
        print("   Format: pitcher_name, line, over_decimal, under_decimal\n")
        print("   Example:")
        print('   STAKE_RAW = """\\')
        print('   Ian Seymour, 5.5, 1.85, 1.82')
        print('   Casey Legumina, 1.5, 2.31, 1.52')
        print('   """')
        return 1

    # -- Parse Stake paste --
    name_to_stake: dict[str, list[Quote]] = {}
    for pitcher_line in raw.splitlines():
        parts = [p.strip() for p in pitcher_line.split(",")]
        if len(parts) != 4:
            print(f"  [SKIP] malformed: {pitcher_line}")
            continue
        name, str_line, str_ov, str_un = parts
        try:
            q = Quote(
                bookmaker="stake",
                line=float(str_line),
                over_odds=decimal_to_american(float(str_ov)),
                under_odds=decimal_to_american(float(str_un)),
            )
        except ValueError:
            print(f"  [SKIP] non-numeric: {pitcher_line}")
            continue
        name_to_stake.setdefault(name.lower(), []).append(q)
        print(f"  STAKE {name:25} L{str_line}  OV {str_ov} ({q.over_odds:+.0f})  "
              f"UN {str_un} ({q.under_odds:+.0f})  vig~{round((1/float(str_ov)+1/float(str_un)-1)*100,1)}%")

    if not name_to_stake:
        print("\nNo valid Stake lines parsed.")
        return 1

    # -- Pull live VPS scan --
    print("\n" + "-" * 70)
    print("Pulling live VPS arb scan (12 books)...")
    try:
        resp = urllib.request.urlopen(
            "https://strike.perfecthold.online/api/v2/arb?bankroll=1000&min_profit_pct=-25",
            timeout=90,
        )
        vps_data = json.load(resp)
    except Exception as e:
        print(f"VPS unreachable: {e}")
        print("Running Stake-only (no arb possible without a second book).")
        vps_data = {"opportunities": []}

    # Extract VPS quotes per pitcher
    vps_by_pitcher: dict[str, list[Quote]] = {}
    for opp in vps_data.get("opportunities", []):
        pname = opp.get("pitcher", "")
        legs = {leg["side"]: leg for leg in opp.get("legs", [])}
        ov, un = legs.get("over", {}), legs.get("under", {})
        if ov and un and opp.get("line"):
            vps_by_pitcher.setdefault(pname, []).append(
                Quote(ov.get("bookmaker", "?"), opp["line"],
                      ov.get("american", 0), un.get("american", 0)))

    print(f"VPS returned {len(vps_by_pitcher)} pitchers "
          f"({vps_data.get('count', 0)} arbs in feed)")

    # -- Match + scan --
    print("\n" + "-" * 70)
    print("ARBITRAGE SCAN (Stake + VPS combined)")
    print(f"{'-' * 70}")

    for pitcher, stake_qs in name_to_stake.items():
        # Fuzzy match by last name substring
        match_name = None
        for vp in vps_by_pitcher:
            # Try last-name match: "Ian Seymour" → "seymour" in "Seymour, Ian" or vice versa
            if pitcher in vp.lower() or vp.lower() in pitcher:
                match_name = vp
                break

        combined = list(stake_qs)
        if match_name:
            combined.extend(vps_by_pitcher[match_name])
            print(f"\n  {pitcher} <- matched VPS '{match_name}'  ({len(combined)} total quotes)")
        else:
            print(f"\n  {pitcher} <- NOT in VPS feed (Stake-only, can't arb)")

        scan_pitcher(pitcher, combined)

    # -- Summary --
    print(f"\n{'=' * 70}")
    print("DONE.")
    print("If no !! above, no Stake cross-venue arb found this run.")
    print("Re-run after the VPS slate fills (typically 12pm-1pm ET / 16:00 UTC).")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
