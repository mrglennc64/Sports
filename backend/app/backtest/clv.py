"""Closing Line Value (CLV) — the sharp's truth metric.

You only know a model has real edge if it consistently bets at better prices than the
market's *closing* line. We can't reconstruct history, so closing lines must be captured
going forward: run ``capture_closing_lines`` shortly before first pitch (e.g. via cron),
then ``clv_for_side`` compares the price we logged against the close.

CLV here is measured in de-vigged probability: positive means the closing market implied
a HIGHER probability for our side than the price we took — i.e. we bought low. Good.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from app.data.names import names_match
from app.data.odds import OddsProvider
from app.model.edge import devig_two_way

CLOSING_FIELDS = ["captured_at", "date", "pitcher", "line", "over_odds", "under_odds"]


def capture_closing_lines(date: str, provider: OddsProvider, path: str) -> int:
    """Snapshot current strikeout props as 'closing' lines. Run near first pitch."""
    rows = []
    stamp = datetime.now(timezone.utc).isoformat()
    for event in provider.list_events():
        try:
            for p in provider.get_strikeout_props(event.event_id):
                rows.append(
                    {
                        "captured_at": stamp,
                        "date": date,
                        "pitcher": p.pitcher_name,
                        "line": p.line,
                        "over_odds": p.over_odds,
                        "under_odds": p.under_odds,
                    }
                )
        except Exception:
            continue

    if not rows:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CLOSING_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def clv_for_side(
    side: str,
    bet_over: float,
    bet_under: float,
    close_over: float,
    close_under: float,
    method: str = "proportional",
) -> float:
    """De-vigged CLV for ``side``: closing prob minus the prob we bet at.

    Positive = the market closed higher on our side than the price we took (value).
    """
    bet_o, bet_u = devig_two_way(bet_over, bet_under, method=method)
    close_o, close_u = devig_two_way(close_over, close_under, method=method)
    if side == "over":
        return close_o - bet_o
    return close_u - bet_u


def find_closing(pitcher: str, date: str, closing_rows: list[dict]) -> dict | None:
    for r in closing_rows:
        if r.get("date") == date and names_match(pitcher, r.get("pitcher", "")):
            return r
    return None
