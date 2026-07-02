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
import math
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
    line: float | None  # the line we bet — must match the captured close to be scored
    clv: float          # de-vigged closing prob for our side minus the prob we took
    beat_close: bool    # clv > 0 -> we bought below where the market closed


@dataclass
class UnmeasurableBet:
    """A flagged bet that matched a close, but at a DIFFERENT line — so CLV can't
    be measured (de-vigging our price against a close at another line compares two
    different bets). Surfaced for transparency, excluded from the aggregates."""
    date: str
    pitcher: str
    side: str
    bet_line: float | None
    close_line: float | None
    reason: str


DECISION_TARGET_N = 200  # decision-grade sample: enough graded bets to trust a keep/kill


@dataclass
class DecisionVerdict:
    """The at-a-glance keep/kill checkpoint for the model's edge.

    CLV is the sample-efficient proof of edge, but a handful of bets prove nothing.
    This asks two honest questions at once: (1) do we have a decision-grade sample
    yet (n vs target), and (2) is the mean CLV *significantly* different from zero
    (95% CI, not just a noisy point estimate)? Only when both hold do we call it.

    status: gathering (below target) | keep | kill | inconclusive (CI straddles 0)
    """
    status: str
    n: int
    target_n: int
    progress_pct: float          # min(1, n / target_n)
    decided: bool                # have we reached a decision-grade sample?
    mean_clv: float | None       # prob-point mean (e.g. 0.004 = +0.4 pts)
    se: float | None             # standard error of the mean
    ci95_low: float | None
    ci95_high: float | None
    signal: str                  # keep / kill / inconclusive from the CI alone
    headline: str                # one-line "N of 200 · mean CLV X · KEEP/KILL"


def clv_decision(clv_values: list[float], target_n: int = DECISION_TARGET_N) -> DecisionVerdict:
    """Turn a set of per-bet CLV values into a keep/kill checkpoint.

    Signal (from the 95% CI on the mean, regardless of sample size):
      keep         -> whole CI above 0  (we significantly beat the close)
      kill         -> whole CI below 0  (we significantly lagged the close)
      inconclusive -> CI straddles 0    (no proven edge either way)

    Status layers the decision-grade sample gate on top: below ``target_n`` we are
    still *gathering* (the signal is shown as a provisional lean, not a verdict);
    at/above it, the signal becomes the final call.
    """
    n = len(clv_values)
    if n == 0:
        return DecisionVerdict(
            status="gathering", n=0, target_n=target_n, progress_pct=0.0,
            decided=False, mean_clv=None, se=None, ci95_low=None, ci95_high=None,
            signal="inconclusive",
            headline=f"0 of {target_n} graded — no measurable CLV yet. Gathering.",
        )

    mean = sum(clv_values) / n
    if n >= 2:
        var = sum((x - mean) ** 2 for x in clv_values) / (n - 1)
        se = math.sqrt(var / n)
    else:
        se = float("inf")
    lo, hi = mean - 1.96 * se, mean + 1.96 * se

    if lo > 0:
        signal = "keep"
    elif hi < 0:
        signal = "kill"
    else:
        signal = "inconclusive"

    decided = n >= target_n
    m = mean * 100
    if not decided:
        lean = {"keep": "leaning KEEP", "kill": "leaning KILL",
                "inconclusive": "no edge yet"}[signal]
        status = "gathering"
        headline = (
            f"{n} of {target_n} graded · mean CLV {m:+.2f} pts · "
            f"NOT YET DECIDED ({lean}) — {target_n - n} more to a call."
        )
    else:
        status = signal
        call = {
            "keep": "KEEP — significantly beats the close",
            "kill": "KILL — significantly lags the close",
            "inconclusive": "INCONCLUSIVE — no proven edge, keep gathering",
        }[signal]
        ci = "" if se == float("inf") else f" (95% CI {lo * 100:+.2f}..{hi * 100:+.2f})"
        headline = (
            f"{n} graded (target {target_n} reached) · mean CLV {m:+.2f} pts{ci} · {call}"
        )

    return DecisionVerdict(
        status=status, n=n, target_n=target_n,
        progress_pct=round(min(1.0, n / target_n), 4),
        decided=decided, mean_clv=round(mean, 4),
        se=None if se == float("inf") else round(se, 4),
        ci95_low=None if se == float("inf") else round(lo, 4),
        ci95_high=None if se == float("inf") else round(hi, 4),
        signal=signal, headline=headline,
    )


@dataclass
class ClvReport:
    n_bets: int                 # flagged bets scored against a SAME-LINE captured close
    n_unmatched: int            # flagged bets with no usable closing line yet
    n_unmeasurable: int         # matched a close, but the line moved -> CLV not valid
    mean_clv: float | None      # headline: average de-vigged CLV (prob points)
    median_clv: float | None
    pct_positive: float | None  # share of scored bets that beat the close
    total_clv: float
    bets: list[ClvBet] = field(default_factory=list)
    unmeasurable: list[UnmeasurableBet] = field(default_factory=list)
    verdict: str = ""
    decision: DecisionVerdict | None = None  # at-a-glance keep/kill checkpoint


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
    target_n: int = DECISION_TARGET_N,
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
    unmeasurable: list[UnmeasurableBet] = []
    unmatched = 0
    for b in bets:
        close = find_closing(b["pitcher"], b["date"], closing)
        if not close or not close.get("over_odds") or not close.get("under_odds"):
            unmatched += 1
            continue

        # CLV is only valid at a SINGLE line. If the line moved between our bet and
        # the captured close, de-vigging our two-way price against the close's
        # two-way price compares two DIFFERENT bets (e.g. under 5.5 vs under 4.5) and
        # yields a sign-confused number. Flag it as unmeasurable rather than fake it.
        bet_line = _to_float(b.get("line"))
        close_line = _to_float(close.get("line"))
        if bet_line is None or close_line is None or abs(bet_line - close_line) > 0.01:
            reason = (
                f"line moved {bet_line:g} -> {close_line:g} between bet and close"
                if bet_line is not None and close_line is not None
                else "line missing on the bet or the captured close"
            )
            unmeasurable.append(UnmeasurableBet(
                date=b.get("date", ""), pitcher=b.get("pitcher", ""), side=b["side"],
                bet_line=bet_line, close_line=close_line, reason=reason,
            ))
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
            line=bet_line, clv=round(clv, 4), beat_close=clv > 0,
        ))

    n_unmeas = len(unmeasurable)
    n = len(scored)
    if n == 0:
        msg = (
            "no flagged bets matched a SAME-LINE captured closing line yet — capture "
            "closing lines near first pitch (line_capture close) so picks can be "
            "scored against the close."
        )
        if n_unmeas:
            msg += (
                f" ({n_unmeas} matched a close but the line had moved, so CLV is not "
                "measurable for them.)"
            )
        return ClvReport(
            0, unmatched, n_unmeas, None, None, None, 0.0, [], unmeasurable, msg,
            decision=clv_decision([], target_n),
        )

    vals = [s.clv for s in scored]
    mean_clv = sum(vals) / n
    pct_pos = sum(1 for s in scored if s.beat_close) / n
    edge = "real price edge" if mean_clv > 0 else "no price edge — picks lagged the close"
    note = "" if n >= 50 else " (small sample — treat as provisional)"
    unmeas_note = (
        f" {n_unmeas} more matched a close at a different line (line moved) and are "
        "excluded as unmeasurable."
        if n_unmeas else ""
    )
    verdict = (
        f"n={n}: mean CLV {mean_clv * 100:+.2f} prob-points, {pct_pos * 100:.0f}% "
        f"of bets beat the close -> {edge}.{note}{unmeas_note}"
    )
    return ClvReport(
        n_bets=n,
        n_unmatched=unmatched,
        n_unmeasurable=n_unmeas,
        mean_clv=round(mean_clv, 4),
        median_clv=round(_median(vals), 4),
        pct_positive=round(pct_pos, 4),
        total_clv=round(sum(vals), 4),
        bets=scored,
        unmeasurable=unmeasurable,
        verdict=verdict,
        decision=clv_decision(vals, target_n),
    )
