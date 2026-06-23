"""CLV / line-movement analysis on captured strikeout-prop history.

Reads line_history.csv (built by app.data.line_capture, run open + close daily),
pairs each pitcher's earliest (open) vs latest (close) capture for a date, de-vigs
both into a fair P(over), and reports:
  - HOW MUCH lines move open->close (the size of the inefficiency = room for CLV),
  - the BIGGEST movers (where sharp money likely came in),
  - and exposes clv_of_pick() — the reusable closing-line-value calc (also the
    exact engine the NHL SOG plan needs in October).

The point: stop trying to PREDICT outcomes; measure whether you can beat the
CLOSE. Positive CLV over many picks is the only non-overfittable proof of edge.

    python clv.py [path_to_line_history.csv]
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict

DEFAULT = "../data/line_history.csv"


def american_to_decimal(a: float) -> float:
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / abs(a)


def fair_over(over_am: float, under_am: float) -> float | None:
    """De-vigged P(over) from a two-sided American price."""
    try:
        io = 1.0 / american_to_decimal(float(over_am))
        iu = 1.0 / american_to_decimal(float(under_am))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return io / (io + iu) if (io + iu) else None


def clv_of_pick(side: str, your_american: float, close_over_am: float,
                close_under_am: float) -> float | None:
    """No-vig CLV of a pick: your price's implied prob vs the de-vigged CLOSE.

    Positive = you beat the close (got a better number than where it settled).
    """
    cf = fair_over(close_over_am, close_under_am)
    if cf is None:
        return None
    close_fair = cf if side == "over" else 1 - cf
    your_imp = 1.0 / american_to_decimal(float(your_american))
    return close_fair - your_imp  # >0: closing fair prob exceeds your break-even


def main(argv: list[str]) -> int:
    path = argv[0] if argv else DEFAULT
    try:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
    except FileNotFoundError:
        print(f"no capture file yet at {path} — run line_capture (open+close) first")
        return 0

    # group by (date, pitcher) -> earliest & latest capture
    # the capture feed names the column "player"; tolerate "pitcher" too
    g = defaultdict(list)
    for r in rows:
        name = r.get("player") or r.get("pitcher") or ""
        g[(r["date"], name)].append(r)

    moves = []  # (date, pitcher, line_open, line_close, fair_open, fair_close)
    for (date, pit), caps in g.items():
        caps.sort(key=lambda r: r["captured_at"])
        o, c = caps[0], caps[-1]
        if o["captured_at"] == c["captured_at"]:
            continue  # only one capture so far — no movement to measure
        fo = fair_over(o["over_odds"], o["under_odds"])
        fc = fair_over(c["over_odds"], c["under_odds"])
        if fo is None or fc is None:
            continue
        moves.append((date, pit, float(o["line"]), float(c["line"]), fo, fc))

    print(f"capture file: {path}   rows {len(rows)}   pitchers paired {len(moves)}")
    if not moves:
        print("Need at least one OPEN and one CLOSE capture per pitcher before there's "
              "movement to analyze. The crons build this over the coming days.")
        return 0

    fair_moves = [abs(m[5] - m[4]) for m in moves]
    line_changed = sum(1 for m in moves if m[2] != m[3])
    print(f"\n=== LINE MOVEMENT (open -> close) ===")
    print(f"  pitchers whose half-point line changed: {line_changed}/{len(moves)}")
    print(f"  fair P(over) move: mean {statistics.mean(fair_moves):.3f}  "
          f"median {statistics.median(fair_moves):.3f}  max {max(fair_moves):.3f}")
    print(f"  => avg available CLV if you front-ran the move: "
          f"~{statistics.mean(fair_moves)*100:.1f}% (upper bound; you can't pick direction)")

    print("\n=== BIGGEST MOVERS (sharp-money candidates) ===")
    for date, pit, lo, lc, fo, fc in sorted(moves, key=lambda m: -abs(m[5]-m[4]))[:8]:
        arrow = "OVER" if fc > fo else "UNDER"
        line = f"{lo}->{lc}" if lo != lc else f"{lo}"
        print(f"  {date} {pit:20} line {line:9} fairP(over) {fo:.2f}->{fc:.2f} "
              f"({(fc-fo)*100:+.0f}pts toward {arrow})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
