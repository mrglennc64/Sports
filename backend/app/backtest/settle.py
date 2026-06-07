"""Settle logged predictions against actual strikeout results.

Reads the predictions CSV, fetches each pitcher's actual strikeouts for that date
from the MLB game log, and decides whether the model's chosen side won. This is the
honesty check the source PDFs kept demanding: did the edges actually cash?
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

from app.data.mlb import MlbClient
from app.model.edge import american_to_decimal


@dataclass
class SettledBet:
    date: str
    pitcher: str
    side: str
    line: float
    odds: float           # American odds for the chosen side
    edge: float
    flagged_bet: bool     # was this a model-flagged bet (bet=True)?
    expected_ks: float
    actual_ks: int
    result: str           # "win" | "loss" | "push"
    profit_units: float   # profit on a 1-unit stake (decimal_odds-1, -1, or 0)


def _side_odds(row: dict) -> float | None:
    side = row.get("side")
    raw = row.get("over_odds") if side == "over" else row.get("under_odds")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def settle_row(row: dict, actual_ks: int) -> SettledBet | None:
    side = row.get("side")
    odds = _side_odds(row)
    try:
        line = float(row["line"])
        edge = float(row.get("edge") or 0.0)
        expected = float(row.get("expected_ks") or 0.0)
    except (TypeError, ValueError, KeyError):
        return None
    if side not in ("over", "under") or odds is None:
        return None

    if actual_ks == line:
        result, profit = "push", 0.0
    else:
        won = (side == "over" and actual_ks > line) or (
            side == "under" and actual_ks < line
        )
        if won:
            result, profit = "win", american_to_decimal(odds) - 1.0
        else:
            result, profit = "loss", -1.0

    return SettledBet(
        date=row.get("date", ""),
        pitcher=row.get("pitcher", ""),
        side=side,
        line=line,
        odds=odds,
        edge=edge,
        flagged_bet=str(row.get("bet")).lower() == "true",
        expected_ks=expected,
        actual_ks=actual_ks,
        result=result,
        profit_units=profit,
    )


def settle_predictions(
    path: str, mlb: MlbClient | None = None
) -> list[SettledBet]:
    mlb = mlb or MlbClient()
    settled: list[SettledBet] = []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Cache actual results per (pitcher_id, date) to avoid duplicate API calls.
    cache: dict[tuple[str, str], int | None] = {}
    for row in rows:
        pid, date = row.get("pitcher_id"), row.get("date")
        if not pid or not date:
            continue
        key = (pid, date)
        if key not in cache:
            try:
                cache[key] = mlb.get_actual_strikeouts(int(pid), date)
            except Exception:
                cache[key] = None
        actual = cache[key]
        if actual is None:  # game not final / pitcher didn't appear yet
            continue
        bet = settle_row(row, actual)
        if bet is not None:
            settled.append(bet)
    return settled
