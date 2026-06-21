"""Line-movement / CLV capture — timestamped strikeout-prop snapshots.

Unlike ``snapshot.py`` (one keep-first capture per day, for backtesting), this
appends EVERY run with a ``captured_at`` timestamp + a ``tag`` (open|close), so we
build a time series of each pitcher's line through the day. That lets us measure:
  - how much lines move open -> close (the size of the inefficiency), and
  - closing-line value (CLV): did a pick beat the close? (the one academically-
    supported, price-based edge — see analytics/clv.py).

Append-only to ``line_history.csv``
(``date,captured_at,tag,pitcher,line,over_odds,under_odds``). Cheap: uses the
single-region props path.

    python -m app.data.line_capture [open|close] [--csv PATH]
"""
from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timezone

from app.config import settings as default_settings
from app.data.odds import get_provider
from app.data.snapshot import _collect_props

FIELDS = ["date", "captured_at", "tag", "pitcher", "line", "over_odds", "under_odds"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Timestamped strikeout-prop capture for CLV.")
    ap.add_argument("tag", nargs="?", default="close", choices=["open", "close"])
    ap.add_argument("--csv", default="../data/line_history.csv")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    provider = get_provider(
        default_settings.odds_provider,
        default_settings.odds_api_key_theoddsapi,
        default_settings.odds_api_key_io,
    )
    props = _collect_props(provider)
    rows = [
        {"date": date_str, "captured_at": ts, "tag": args.tag,
         "pitcher": p.pitcher_name, "line": p.line,
         "over_odds": p.over_odds, "under_odds": p.under_odds}
        for p in props
    ]

    parent = os.path.dirname(args.csv)
    if parent:
        os.makedirs(parent, exist_ok=True)
    is_new = not os.path.exists(args.csv)
    with open(args.csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerows(rows)
    print(f"[{ts}] line_capture {args.tag}: {len(rows)} props -> {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
