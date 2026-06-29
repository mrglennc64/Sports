"""Out-of-sample validation of probability calibrators.

The neighbours answer "is the model calibrated?" (reliability.py) and apply a
fixed shrink (model/calibration.py). This module answers the question that has to
be settled *before* any calibrator is allowed to touch staking:

    "Does recalibrating actually help on data it was NOT fit to?"

``best_shrink`` (model/calibration.py) and the weekly report fit the shrink factor
on the *same* graded sample they score — that is in-sample and will always look as
good or better than doing nothing. The only honest test is out-of-sample: fit the
calibrator on an earlier slice of graded predictions, then score it on a later,
unseen slice. This module does a **chronological** train/test split (no leakage,
respects the arrow of time the way a live deploy would) and compares three options
on the held-out test set:

  * baseline  — raw model probabilities, no calibration (k = 1.0)
  * shrink    — 1-parameter shrink-to-even, k fit on train (model/calibration.py)
  * platt     — 2-parameter logistic recalibration, (a, b) fit on train

All three are monotonic, so none can produce the non-monotonic per-band lookup
that small-sample reliability curves tempt you into (a 0.85 band that "wins 0%" on
n=1 must NOT become a rule). The recommendation is deliberately conservative: it
only endorses turning calibration on when the held-out improvement clears a margin
AND the sample is large enough to mean something. Nothing here changes staking —
it produces evidence for the operator to set ``PROB_SHRINKAGE`` (or, if platt wins
clearly, to justify wiring platt into bridge.py behind its own default-off flag).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.backtest.settle import SettledBet
from app.model.calibration import best_shrink, shrink_to_even

_EPS = 1e-9

# Below this many decided predictions the OOS read is variance, not signal — the
# same spirit as reliability._verdict's n<100 guard, raised because a train/test
# split spends half the sample on fitting.
_MIN_N_FOR_VERDICT = 200
_MIN_TEST_N = 50
# Required held-out log-loss improvement (vs baseline) before we endorse turning a
# calibrator on. A hair of improvement on a thin sample is noise, not evidence.
_MIN_LOGLOSS_GAIN = 0.01


def _clamp01(x: float) -> float:
    return min(1.0 - _EPS, max(_EPS, x))


def _logit(p: float) -> float:
    p = _clamp01(p)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def pairs_with_dates(settled: list[SettledBet]) -> list[tuple[str, float, int]]:
    """(date, model_prob_of_chosen_side, won) for decided, prob-carrying picks.

    Mirrors reliability._usable but keeps the date so callers can split in time.
    Pushes and rows logged before model_prob existed carry no signal and are dropped.
    """
    out: list[tuple[str, float, int]] = []
    for s in settled:
        if s.result == "push" or s.model_prob is None:
            continue
        out.append((s.date, _clamp01(float(s.model_prob)), 1 if s.result == "win" else 0))
    return out


def platt_fit(
    pairs: list[tuple[float, int]], iters: int = 50, ridge: float = 1e-3
) -> tuple[float, float]:
    """Fit p_cal = sigmoid(a + b * logit(p_raw)) by Newton-Raphson (IRLS).

    Two parameters: ``a`` corrects bias, ``b`` corrects over/under-confidence.
    Perfect calibration is (a, b) = (0, 1). A small ridge on the deviation from
    that identity keeps the fit finite when the graded sample is (near-)separable
    — which is exactly the regime a small sports sample lives in (e.g. a high-prob
    band that happens to be 10/10). ``b`` is clamped >= 0 so the calibrator can
    never invert the model into an anti-signal; the result is always monotonic.
    """
    xs = [_logit(p) for p, _ in pairs]
    ys = [float(y) for _, y in pairs]
    a, b = 0.0, 1.0  # start at identity (no recalibration)
    for _ in range(iters):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            q = _sigmoid(a + b * x)
            d = q - y
            w = max(q * (1.0 - q), _EPS)
            g0 += d
            g1 += d * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        # Ridge pulls the *solution* toward identity (a=0, b=1), not toward 0.
        g0 += ridge * (a - 0.0)
        g1 += ridge * (b - 1.0)
        h00 += ridge
        h11 += ridge
        det = h00 * h11 - h01 * h01
        if abs(det) < _EPS:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a -= da
        b -= db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, max(0.0, b)


def apply_platt(p: float, a: float, b: float) -> float:
    """Calibrated probability under a fitted Platt (a, b). Monotonic in p, clamped."""
    return _clamp01(_sigmoid(a + b * _logit(p)))


def _score(cal_pairs: list[tuple[float, int]], n_bins: int = 10) -> dict:
    """Brier, log-loss, ECE for already-calibrated (prob, outcome) pairs."""
    n = len(cal_pairs)
    if n == 0:
        return {"n": 0, "brier": None, "log_loss": None, "ece": None}
    brier = sum((p - y) ** 2 for p, y in cal_pairs) / n
    log_loss = sum(
        -(y * math.log(_clamp01(p)) + (1 - y) * math.log(_clamp01(1 - p)))
        for p, y in cal_pairs
    ) / n
    groups: dict[int, list[tuple[float, int]]] = {}
    for p, y in cal_pairs:
        groups.setdefault(min(int(p * n_bins), n_bins - 1), []).append((p, y))
    ece = 0.0
    for g in groups.values():
        m = len(g)
        avg_p = sum(p for p, _ in g) / m
        rate = sum(y for _, y in g) / m
        ece += m * abs(rate - avg_p)
    ece /= n
    return {
        "n": n,
        "brier": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "ece": round(ece, 4),
    }


@dataclass
class CalibrationValidation:
    n_total: int
    n_train: int
    n_test: int
    train_date_range: tuple[str, str] | None
    test_date_range: tuple[str, str] | None
    temporal_holdout: bool = True   # False => train/test share dates (one slate, not a real OOS)
    fitted: dict = field(default_factory=dict)   # {"shrink_k": .., "platt_a": .., "platt_b": ..}
    test_scores: dict = field(default_factory=dict)  # {"baseline": {...}, "shrink": {...}, "platt": {...}}
    recommendation: str = ""
    recommended_method: str = "none"


def oos_validate(
    settled: list[SettledBet], train_frac: float = 0.7, n_bins: int = 10
) -> CalibrationValidation:
    """Chronological-split out-of-sample comparison of the calibrators.

    Fit on the earliest ``train_frac`` of decided predictions, score on the rest.
    Returns held-out Brier/log-loss/ECE for baseline, shrink, and platt plus a
    conservative recommendation. Never mutates staking; pure read/compute.
    """
    rows = pairs_with_dates(settled)
    rows.sort(key=lambda r: r[0])  # by date (ISO YYYY-MM-DD sorts chronologically)
    n_total = len(rows)

    if n_total < _MIN_TEST_N * 2:
        return CalibrationValidation(
            n_total=n_total, n_train=0, n_test=0,
            train_date_range=None, test_date_range=None,
            recommendation=(
                f"n={n_total}: too few decided predictions to validate out-of-sample. "
                f"Keep PROB_SHRINKAGE off (1.0); revisit at >= {_MIN_N_FOR_VERDICT}."
            ),
        )

    cut = int(n_total * train_frac)
    train, test = rows[:cut], rows[cut:]
    train_pairs = [(p, y) for _, p, y in train]
    test_pairs = [(p, y) for _, p, y in test]

    # A chronological split only buys a real out-of-sample read if the test slice
    # contains day(s) the fit never saw. If every graded prediction is from one slate
    # (the n=147-on-one-date case), this is a random within-slate cut, not a temporal
    # holdout — any "gain" is in-sample and must not be acted on. A single shared
    # boundary day is fine; what matters is that some test dates are genuinely new.
    temporal_holdout = bool(
        set(d for d, _, _ in test) - set(d for d, _, _ in train)
    )
    overlap_note = (
        ""
        if temporal_holdout
        else " [NOTE: train and test share date(s) -- this is one slate cut at random, "
             "NOT a temporal holdout; treat any improvement as in-sample only.]"
    )

    k, _ = best_shrink([(p, bool(y)) for p, y in train_pairs])
    a, b = platt_fit(train_pairs)

    base_test = _score(test_pairs, n_bins)
    shrink_test = _score([(shrink_to_even(p, k), y) for p, y in test_pairs], n_bins)
    platt_test = _score([(apply_platt(p, a, b), y) for p, y in test_pairs], n_bins)

    scores = {"baseline": base_test, "shrink": shrink_test, "platt": platt_test}

    # Recommend by held-out log-loss, but only if it clears the margin AND the
    # sample is big enough to trust. Ties / thin samples -> keep calibration off.
    best_method, best_ll = "baseline", base_test["log_loss"]
    for name in ("shrink", "platt"):
        ll = scores[name]["log_loss"]
        if ll is not None and best_ll is not None and ll < best_ll:
            best_method, best_ll = name, ll

    gain = (base_test["log_loss"] - best_ll) if (best_ll is not None) else 0.0
    if not temporal_holdout:
        # No real time separation -> cannot trust OOS at all, regardless of gain.
        rec_method = "none"
        rec = (
            f"n={n_total}: all graded predictions fall on the same date(s), so there is no "
            f"out-of-sample test to be had yet -- the model has only been graded on one slate. "
            f"Keep PROB_SHRINKAGE off until several days of slates are graded."
        )
    elif n_total < _MIN_N_FOR_VERDICT or len(test) < _MIN_TEST_N:
        rec_method = "none"
        rec = (
            f"n={n_total} (test={len(test)}): provisional -- below the {_MIN_N_FOR_VERDICT}-sample "
            f"bar for a trustworthy OOS verdict. Best held-out method so far is "
            f"'{best_method}' (log-loss gain {gain:+.3f} vs baseline), but DO NOT enable yet."
        )
    elif best_method == "baseline" or gain < _MIN_LOGLOSS_GAIN:
        rec_method = "none"
        rec = (
            f"n={n_total}: no calibrator beats baseline out-of-sample by the required "
            f"{_MIN_LOGLOSS_GAIN:.2f} log-loss margin (best '{best_method}', gain {gain:+.3f}). "
            f"Keep PROB_SHRINKAGE off -- recalibrating here would be fitting noise."
        )
    elif best_method == "shrink":
        rec_method = "shrink"
        rec = (
            f"n={n_total}: shrink-to-even (k={k:.2f}) improves held-out log-loss by "
            f"{gain:.3f}. Recommend setting PROB_SHRINKAGE={k:.2f} in prod and re-checking "
            f"/calibration after the next slates."
        )
    else:
        rec_method = "platt"
        rec = (
            f"n={n_total}: Platt (a={a:.2f}, b={b:.2f}) improves held-out log-loss by "
            f"{gain:.3f}, beating 1-param shrink. Justifies wiring a fitted Platt into "
            f"bridge.py behind a new default-off flag; verify again as the sample grows."
        )

    return CalibrationValidation(
        n_total=n_total, n_train=len(train), n_test=len(test),
        train_date_range=(train[0][0], train[-1][0]),
        test_date_range=(test[0][0], test[-1][0]),
        temporal_holdout=temporal_holdout,
        fitted={"shrink_k": round(k, 4), "platt_a": round(a, 4), "platt_b": round(b, 4)},
        test_scores=scores,
        recommendation=rec + overlap_note,
        recommended_method=rec_method,
    )
