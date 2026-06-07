"""CLI: settle logged predictions and print a backtest report.

    python -m app.backtest.run [predictions.csv]

Settles each prediction against actual strikeouts and reports hit-rate, ROI and MAE.
Only games that are final contribute; today's un-played slate is skipped automatically.
"""
from __future__ import annotations

import sys

from app.backtest.metrics import summarize
from app.backtest.settle import settle_predictions
from app.config import settings


def main(path: str | None = None) -> None:
    path = path or settings.predictions_log
    settled = settle_predictions(path)
    report = summarize(settled)

    print(f"Backtest of {path}")
    print(f"  settled predictions : {report.n_predictions}")
    print(f"  flagged bets         : {report.n_bets} "
          f"({report.wins}W-{report.losses}L-{report.pushes}P)")
    if report.hit_rate is not None:
        print(f"  hit rate             : {report.hit_rate * 100:.1f}%")
    if report.roi is not None:
        print(f"  ROI                  : {report.roi * 100:+.1f}% "
              f"({report.total_profit_units:+.2f} units)")
    if report.mae is not None:
        print(f"  model MAE (Ks)       : {report.mae:.2f}")
    if report.n_predictions == 0:
        print("  (no final games yet — settle past dates once games complete)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
