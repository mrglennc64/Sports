"""Append evaluated predictions to a CSV log.

This is the seed for the future backtest / CLV layer: without a record of what the
model said (line, probability, edge) at prediction time, "edge" can never be checked
against results or closing lines. Every evaluated start is logged once.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

FIELDS = [
    "logged_at",
    "date",
    "pitcher",
    "pitcher_id",
    "game_pk",
    "opponent",
    "venue",
    "expected_ks",
    "line",
    "bookmaker",
    "side",
    "model_prob",
    "fair_prob",
    "over_odds",
    "under_odds",
    "edge",
    "kelly",
    "bet",
    "low_confidence",
]


def log_predictions(rows: list[dict], path: str) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new_file = not os.path.exists(path)
    stamp = datetime.now(timezone.utc).isoformat()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow({"logged_at": stamp, **row})
