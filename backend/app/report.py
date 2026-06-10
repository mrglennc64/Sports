"""One-command backtest report — grade the model's leans against REAL outcomes.

This is the antidote to trusting the live slate's confident-looking edges. It
loads the accumulated lines (data/lines.csv), pulls each pitcher's ACTUAL
strikeouts from the MLB API, has the v2 model lean its own side, and measures
whether those leans actually win — plus a calibration table that exposes
overconfidence (if "10%+ edge" plays don't win near their implied rate, the
edges are fake).

Run it:  python -m app.report [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--lines PATH]
With no dates it covers the full span present in the lines file.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass

from app.config import settings as default_settings
from app.data.client import StatsApiClient
from app.data.history import load_history_range, load_lines_csv
from app.model import poisson
from app.model.backtest import GameOutcome, run_backtest
from app.model.projection import project
from app.model.weights import ModelConfig

# Break-even win probability at standard -110 juice (risk 110 to win 100).
BREAK_EVEN_110 = 110 / 210  # ~0.5238
WIN_UNITS_110 = 100 / 110   # ~0.909 profit per 1u risked on a -110 winner


@dataclass
class GradedBet:
    pitcher: str
    line: float
    lam: float
    lean: str           # "over" | "under"
    model_prob: float   # model P(leaned side)
    edge: float         # model_prob - BREAK_EVEN_110
    actual_ks: int
    outcome: str        # "win" | "loss" | "push"
    units: float        # at -110


def grade_outcome(go: GameOutcome, cfg: ModelConfig | None = None) -> GradedBet | None:
    """Lean the model's side on a graded game and score it at -110. None if no line."""
    if go.line is None:
        return None
    lam = project(go.inputs, cfg).projected_ks
    p_over = poisson.prob_over(lam, go.line)
    p_under = poisson.prob_under(lam, go.line)
    lean, model_prob = ("over", p_over) if p_over >= p_under else ("under", p_under)

    actual = go.actual_ks
    if actual == go.line:
        outcome, units = "push", 0.0
    elif (lean == "over" and actual > go.line) or (lean == "under" and actual < go.line):
        outcome, units = "win", WIN_UNITS_110
    else:
        outcome, units = "loss", -1.0

    return GradedBet(
        pitcher=go.inputs.pitcher_name,
        line=go.line,
        lam=lam,
        lean=lean,
        model_prob=model_prob,
        edge=model_prob - BREAK_EVEN_110,
        actual_ks=actual,
        outcome=outcome,
        units=units,
    )


def calibration_table(bets: list[GradedBet]) -> list[dict]:
    """Bucket +EV plays by model edge; show implied vs actual win rate.

    The honesty check: if the actual win rate in a bucket is far below the
    model's average implied probability there, the model is overconfident.
    """
    buckets = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01)]
    rows = []
    for lo, hi in buckets:
        plays = [b for b in bets if lo <= b.edge < hi and b.outcome != "push"]
        if not plays:
            continue
        wins = sum(1 for b in plays if b.outcome == "win")
        rows.append({
            "bucket": f"{lo:.0%}-{hi:.0%}",
            "plays": len(plays),
            "implied_win": sum(b.model_prob for b in plays) / len(plays),
            "actual_win": wins / len(plays),
            "units": sum(b.units for b in plays),
        })
    return rows


def render_report(start: str, end: str, dataset: list[GameOutcome]) -> str:
    graded = [g for go in dataset if (g := grade_outcome(go)) is not None]
    acc = run_backtest(dataset).accuracy

    lines = []
    lines.append(f"BACKTEST REPORT  {start} -> {end}")
    lines.append(f"  games graded: {acc.n}   (with a line: {len(graded)})")
    lines.append("")
    lines.append("ACCURACY (model projection vs actual Ks)")
    lines.append(f"  MAE  {acc.mae:.2f}   RMSE {acc.rmse:.2f}   bias {acc.bias:+.2f}"
                 f"  ({'over' if acc.bias > 0 else 'under'}-projecting)")

    if graded:
        plays = [b for b in graded if b.edge > 0 and b.outcome != "push"]
        w = sum(1 for b in plays if b.outcome == "win")
        l = sum(1 for b in plays if b.outcome == "loss")
        u = sum(b.units for b in plays)
        lines.append("")
        lines.append("MODEL +EV PLAYS (leaned side has positive edge at -110)")
        if plays:
            lines.append(f"  record {w}-{l}   win% {w / (w + l):.1%}   "
                         f"units {u:+.2f}   ROI {u / (w + l):+.1%}")
            lines.append(f"  (break-even win% at -110 is {BREAK_EVEN_110:.1%})")
        else:
            lines.append("  none")

        lines.append("")
        lines.append("CALIBRATION (are the edges real?)  edge | plays | implied vs ACTUAL win% | units")
        cal = calibration_table(graded)
        if cal:
            for r in cal:
                lines.append(f"  {r['bucket']:>9} | {r['plays']:>4} | "
                             f"{r['implied_win']:.0%} vs {r['actual_win']:.0%} | {r['units']:+.2f}")
        else:
            lines.append("  (no +EV plays to bucket yet)")

    n = len(graded)
    lines.append("")
    if n < 100:
        lines.append(f"  ⚠  n={n}. Far too small to conclude anything — this is variance, "
                     "not edge. Keep accumulating; revisit at a few hundred graded bets.")
    return "\n".join(lines)


def _line_date_bounds(path: str) -> tuple[str, str]:
    dates = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("date") or "").strip()
            if d:
                dates.append(d)
    if not dates:
        raise SystemExit(f"no dated rows in {path}")
    return min(dates), max(dates)


async def build_report(start: str, end: str, lines_path: str,
                       client: StatsApiClient | None = None) -> str:
    owns = client is None
    client = client or StatsApiClient()
    try:
        lines = load_lines_csv(lines_path)
        dataset = await load_history_range(client, start, end, lines=lines)
        return render_report(start, end, dataset)
    finally:
        if owns:
            await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grade the model against real outcomes.")
    parser.add_argument("--lines", default=default_settings.lines_csv)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args(argv)

    lo, hi = _line_date_bounds(args.lines)
    start, end = args.start or lo, args.end or hi
    print(asyncio.run(build_report(start, end, args.lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
