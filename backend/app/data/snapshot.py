"""Daily snapshot of current strikeout prop lines -> a growing CSV history.

There is no free source of *historical* / closing pitcher-strikeout prop lines,
so we build our own: run this once a day (ideally at a consistent time near
first pitch — that captures your "close") and it appends today's lines to a CSV
that :func:`app.data.history.load_lines_csv` reads back for backtesting.

Each prop is matched to the day's probable start so the CSV stores the MLB
pitcher **id** (not the sportsbook's name spelling), which the history loader
keys on exactly — sidestepping name-matching entirely. If no probable start
matches, the pitcher's name is stored as a fallback.

CSV columns (matches the history loader): ``date,pitcher,line,over_odds,under_odds``.
Re-running for the same date is idempotent: pitchers already recorded that day
are skipped, so the first capture of the day is the one that sticks.

Run it:  ``python -m app.data.snapshot [--date YYYY-MM-DD] [--csv PATH]``
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from datetime import date as date_cls

from app.config import Settings
from app.config import settings as default_settings
from app.data.client import StatsApiClient
from app.data.mlb_stats import fetch_probable_starts
from app.data.names import names_match
from app.data.odds import OddsProvider, PropLine, get_provider

CSV_FIELDS = ["date", "pitcher", "line", "over_odds", "under_odds"]


def _collect_props(provider: OddsProvider) -> list[PropLine]:
    props: list[PropLine] = []
    for event in provider.list_events():
        try:
            props.extend(provider.get_strikeout_props(event.event_id))
        except Exception:  # one bad event shouldn't sink the snapshot
            continue
    return props


def _existing_keys(csv_path: str) -> set[tuple[str, str]]:
    """(date, pitcher) pairs already in the CSV, so re-runs don't duplicate."""
    if not os.path.exists(csv_path):
        return set()
    keys: set[tuple[str, str]] = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("date") or "").strip()
            p = (row.get("pitcher") or "").strip()
            if d and p:
                keys.add((d, p))
    return keys


def _append_rows(csv_path: str, rows: list[dict]) -> None:
    if not rows:
        return
    parent = os.path.dirname(csv_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


async def snapshot_lines(
    on_date: str,
    csv_path: str,
    *,
    client: StatsApiClient | None = None,
    provider: OddsProvider | None = None,
    settings: Settings = default_settings,
) -> int:
    """Append today's strikeout prop lines to ``csv_path``. Returns rows written.

    Pitchers already recorded for ``on_date`` are skipped (idempotent re-run).
    """
    owns = client is None
    client = client or StatsApiClient()
    provider = provider or get_provider(
        settings.odds_provider,
        settings.odds_api_key_theoddsapi,
        settings.odds_api_key_io,
    )
    try:
        starts = await fetch_probable_starts(client, on_date)
        props = _collect_props(provider)
        existing = _existing_keys(csv_path)

        rows: list[dict] = []
        for prop in props:
            start = next(
                (s for s in starts if names_match(s.pitcher_name, prop.pitcher_name)),
                None,
            )
            pitcher_field = str(start.pitcher_id) if start else prop.pitcher_name
            key = (on_date, pitcher_field)
            if key in existing:
                continue
            existing.add(key)
            rows.append({
                "date": on_date,
                "pitcher": pitcher_field,
                "line": prop.line,
                "over_odds": prop.over_odds,
                "under_odds": prop.under_odds,
            })

        _append_rows(csv_path, rows)
        return len(rows)
    finally:
        if owns:
            await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot today's strikeout prop lines to CSV.")
    parser.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD (default: today)")
    parser.add_argument("--csv", default=default_settings.lines_csv, help="Output CSV path")
    args = parser.parse_args(argv)

    written = asyncio.run(snapshot_lines(args.date, args.csv))
    print(f"Wrote {written} new line(s) for {args.date} to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
