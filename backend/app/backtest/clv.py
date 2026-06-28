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
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.data.names import names_match
from app.data.odds import OddsProvider
from app.model.edge import devig_two_way

CLOSING_FIELDS = ["captured_at", "date", "pitcher", "line", "over_odds", "under_odds"]

_TRUE = {"true", "1", "yes"}


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


# --------------------------------------------------------------------------- #
# Aggregate CLV across the prediction log (the /clv scoreboard)
# --------------------------------------------------------------------------- #
@dataclass
class ClvBet:
    date: str
    pitcher: str
    side: str
    clv: float          # de-vigged closing prob for our side minus the prob we took
    beat_close: bool    # clv > 0 -> we bought below where the market closed


@dataclass
class ClvReport:
    n_bets: int                 # flagged bets matched to a captured closing line
    n_unmatched: int            # flagged bets with no usable closing line yet
    mean_clv: float | None      # headline: average de-vigged CLV (prob points)
    median_clv: float | None
    pct_positive: float | None  # share of matched bets that beat the close
    total_clv: float
    bets: list[ClvBet] = field(default_factory=list)
    verdict: str = ""


def _flagged_bets(predictions_log: str) -> list[dict]:
    """Logged rows that were actually flagged as bets and carry both prices.

    CLV is only meaningful for picks we'd have taken at a price; de-vig needs both
    sides, so rows missing either are skipped (e.g. parlay legs log one side only).
    """
    if not os.path.exists(predictions_log):
        return []
    out: list[dict] = []
    with open(predictions_log, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("bet", "")).strip().lower() not in _TRUE:
                continue
            if r.get("side") not in ("over", "under"):
                continue
            if not r.get("over_odds") or not r.get("under_odds"):
                continue
            out.append(r)
    return out


def _load_closing(line_history_path: str) -> list[dict]:
    """Close-tagged line snapshots, latest-first so find_closing picks the close.

    Accepts both the tagged ``line_history.csv`` (open|close) and an untagged
    closing file; when a ``tag`` column exists, only ``close`` rows are kept.
    """
    if not os.path.exists(line_history_path):
        return []
    with open(line_history_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    has_tag = any("tag" in r for r in rows)
    if has_tag:
        rows = [r for r in rows if str(r.get("tag", "")).strip().lower() == "close"]
    # Latest capture first, so the first name+date match is the true close.
    rows.sort(key=lambda r: r.get("captured_at", ""), reverse=True)
    return rows


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def clv_report(
    predictions_log: str,
    line_history_path: str,
    method: str = "proportional",
) -> ClvReport:
    """Score flagged bets against captured closing lines — the price-based edge.

    Joins each flagged bet to its closing line (by date + pitcher name), computes
    de-vigged CLV for the side we took, and aggregates. Positive mean CLV is the
    one academically-supported signal of real edge: we consistently bought below
    where the market closed.
    """
    bets = _flagged_bets(predictions_log)
    closing = _load_closing(line_history_path)

    scored: list[ClvBet] = []
    unmatched = 0
    for b in bets:
        close = find_closing(b["pitcher"], b["date"], closing)
        if not close or not close.get("over_odds") or not close.get("under_odds"):
            unmatched += 1
            continue
        try:
            clv = clv_for_side(
                b["side"],
                float(b["over_odds"]), float(b["under_odds"]),
                float(close["over_odds"]), float(close["under_odds"]),
                method=method,
            )
        except (ValueError, TypeError, ZeroDivisionError):
            unmatched += 1
            continue
        scored.append(ClvBet(
            date=b.get("date", ""), pitcher=b.get("pitcher", ""), side=b["side"],
            clv=round(clv, 4), beat_close=clv > 0,
        ))

    n = len(scored)
    if n == 0:
        msg = (
            "no flagged bets matched a captured closing line yet — capture "
            "closing lines near first pitch (line_capture close) so picks can be "
            "scored against the close."
        )
        return ClvReport(0, unmatched, None, None, None, 0.0, [], msg)

    vals = [s.clv for s in scored]
    mean_clv = sum(vals) / n
    pct_pos = sum(1 for s in scored if s.beat_close) / n
    edge = "real price edge" if mean_clv > 0 else "no price edge — picks lagged the close"
    note = "" if n >= 50 else " (small sample — treat as provisional)"
    verdict = (
        f"n={n}: mean CLV {mean_clv * 100:+.2f} prob-points, {pct_pos * 100:.0f}% "
        f"of bets beat the close -> {edge}.{note}"
    )
    return ClvReport(
        n_bets=n,
        n_unmatched=unmatched,
        mean_clv=round(mean_clv, 4),
        median_clv=round(_median(vals), 4),
        pct_positive=round(pct_pos, 4),
        total_clv=round(sum(vals), 4),
        bets=scored,
        verdict=verdict,
    )
