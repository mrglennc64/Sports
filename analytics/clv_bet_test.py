"""CLV test: did your model's picks beat the close?

Matches lines.csv (your bets) against line_history.csv (open→close captures)
and computes CLV for every pick where both exist.

CLV > 0 = you got a better price than where the market settled (edge).
CLV < 0 = the market moved against your pick (no edge).
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime


def american_to_decimal(a: float) -> float:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return 1.0
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / abs(a)


def fair_over(over_am, under_am) -> float | None:
    """De-vigged P(over) from a two-sided American price."""
    try:
        io = 1.0 / american_to_decimal(float(over_am))
        iu = 1.0 / american_to_decimal(float(under_am))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    total = io + iu
    return io / total if total else None


def clv_of_pick(side: str, your_american, close_over_am, close_under_am) -> float | None:
    """No-vig CLV: closing fair prob of your side minus your price's implied prob.
    Positive = you beat the close."""
    cf = fair_over(close_over_am, close_under_am)
    if cf is None:
        return None
    close_fair = cf if side == "over" else 1 - cf
    try:
        your_imp = 1.0 / american_to_decimal(float(your_american))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return close_fair - your_imp


def main() -> int:
    lines_path = sys.argv[1] if len(sys.argv) > 1 else "../data/lines_remote.csv"
    history_path = sys.argv[2] if len(sys.argv) > 2 else "../data/line_history_remote.csv"

    # ── Load lines (bets) ──
    try:
        bet_rows = list(csv.DictReader(open(lines_path, encoding="utf-8")))
    except FileNotFoundError:
        print(f"Lines file not found: {lines_path}")
        return 1

    # ── Load close captures ──
    try:
        hist_rows = list(csv.DictReader(open(history_path, encoding="utf-8")))
    except FileNotFoundError:
        print(f"History file not found: {history_path}")
        return 1

    # Index close captures by (date, pitcher) → latest close row
    close_index: dict[tuple[str, str], dict] = {}
    for r in hist_rows:
        if r.get("tag") != "close":
            continue
        key = (r["date"], r.get("pitcher", "").lower())
        # Keep latest close capture per date
        if key not in close_index or r["captured_at"] > close_index[key]["captured_at"]:
            close_index[key] = r

    # ── Build picks from lines.csv ──
    # A row with only one side filled = the model's bet
    # Later rows have both sides (snapshot); we skip those for CLV testing
    picks = []
    for r in bet_rows:
        date = r["date"]
        pitcher = r.get("pitcher", "").strip()
        over_odds = r.get("over_odds", "").strip()
        under_odds = r.get("under_odds", "").strip()

        # Determine side and odds from the row
        has_over = bool(over_odds)
        has_under = bool(under_odds)

        if has_over and has_under:
            # Two-sided — not a pick, just a line capture. Skip.
            continue
        if not has_over and not has_under:
            continue

        side = "over" if has_over else "under"
        your_odds = float(over_odds if has_over else under_odds)

        picks.append({
            "date": date,
            "pitcher": pitcher,
            "side": side,
            "your_odds": your_odds,
            "line": r.get("line", "").strip(),
        })

    if not picks:
        print("No one-sided bet rows found in lines.csv (no model picks to test).")
        return 1

    # ── Match picks against close lines ──
    results = []
    unmatched = 0
    for p in picks:
        key = (p["date"], p["pitcher"].lower())
        close_row = close_index.get(key)
        if not close_row:
            unmatched += 1
            continue

        clv = clv_of_pick(
            p["side"],
            p["your_odds"],
            close_row["over_odds"],
            close_row["under_odds"],
        )
        if clv is None:
            unmatched += 1
            continue

        results.append({
            **p,
            "close_over": float(close_row["over_odds"]),
            "close_under": float(close_row["under_odds"]),
            "clv": clv,
        })

    # ── Report ──
    print("=" * 70)
    print("CLV BET TEST: Did your picks beat the close?")
    print("=" * 70)
    print(f"Bets found: {len(picks)}")
    print(f"Close lines matched: {len(results)}")
    print(f"Unmatched (no close data): {unmatched}")
    print()

    if not results:
        print("No matches between bet history and close captures. Need more overlap.")
        return 0

    clv_values = [r["clv"] for r in results]
    pos_clv = sum(1 for v in clv_values if v > 0)
    neg_clv = sum(1 for v in clv_values if v < 0)
    zero_clv = sum(1 for v in clv_values if v == 0)
    mean_clv = statistics.mean(clv_values)
    median_clv = statistics.median(clv_values)

    print(f"RESULTS ({len(results)} graded picks):")
    print(f"  Positive CLV (beat close):  {pos_clv}  ({pos_clv/len(results)*100:.0f}%)")
    print(f"  Negative CLV (lost to close): {neg_clv}  ({neg_clv/len(results)*100:.0f}%)")
    print(f"  Flat:                       {zero_clv}")
    print(f"  Mean CLV:   {mean_clv:+.3f}  ({mean_clv*100:+.1f}%)")
    print(f"  Median CLV: {median_clv:+.3f}  ({median_clv*100:+.1f}%)")
    print()

    if mean_clv > 0.005:
        print("VERDICT: Positive CLV — your picks are beating the close. Edge confirmed.")
    elif mean_clv > -0.005:
        print("VERDICT: Neutral CLV — your picks are roughly at market. No edge either way.")
    else:
        print("VERDICT: Negative CLV — the market moves AGAINST your picks. No edge.")

    print()
    print("--- PER-PICK DETAIL ---")
    print(f"{'Date':12} {'Pitcher':22} {'Side':5} {'Your':>6} {'CloseOV':>6} {'CloseUN':>6} {'CLV':>7}")
    print("-" * 75)
    for r in sorted(results, key=lambda x: x["clv"], reverse=True):
        your_str = f"{r['your_odds']:+.0f}" if r['your_odds'] > 0 else str(int(r['your_odds']))
        print(f"{r['date']:12} {r['pitcher']:22} {r['side']:5} {your_str:>6} "
              f"{r['close_over']:>+6.0f} {r['close_under']:>+6.0f} {r['clv']:>+7.3f}")

    print()
    print("--- BY DATE ---")
    by_date = defaultdict(list)
    for r in results:
        by_date[r["date"]].append(r["clv"])
    for d in sorted(by_date):
        vals = by_date[d]
        print(f"  {d}: n={len(vals):2}  mean_clv={statistics.mean(vals):+.3f}  "
              f"pos={sum(1 for v in vals if v>0)}/{len(vals)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
