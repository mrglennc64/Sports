"""Group-vs-group strikeout PRIOR + out-of-sample (OOS) validation gate.

This is the consumer side of the offline grouping engine. A parallel task builds
the *group-vs-group* strikeout matrix (clusters -> matchup K-rates); this module
turns that matrix into a per-start expected-strikeouts PRIOR, and — crucially —
provides an HONEST out-of-sample scorer that decides whether the prior is worth
wiring into production at all.

Discipline (same as the earlier archetype model that was DISABLED at MAE 1.57 vs a
naive 1.43): the prior only ships if it beats a naive baseline OUT OF SAMPLE. The
functions here build the gate; they do not assert the gate passes.

Contract with the parallel "matrix" task
-----------------------------------------
matchup_matrix.parquet has columns:
    pitcher_group, batter_group, n_pa, k_rate_raw, k_rate_shrunk, global_rate
and there is a lookup ``matchup_k_rate(matrix, pgroup, bgroup) -> rate``.

To keep THIS module unit-testable without depending on the (still-landing) matrix
module, we provide a local ``matchup_k_rate`` that reads exactly that documented
schema, preferring the shrunk rate and falling back to ``global_rate`` when a cell
is missing. If/when the parallel module ships its own lookup, callers may pass it
in via the ``lookup`` parameter — the scoring math is identical either way.

Design seam
-----------
The PURE scoring math (``expected_ks_prior``, ``mae``, ``score_predictions``) takes
plain arrays / a plain DataFrame and has NO file I/O, so it is fully unit-testable.
The heavy data-loading (Retrosheet starts, matrix build) lives in clearly-separated
loader functions used only by ``evaluate_prior_oos``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from app.grouping.retrosheet import DATA_DIR, plays_path

# ---------------------------------------------------------------------------
# Matrix schema + lookup (mirrors the parallel task's contract)
# ---------------------------------------------------------------------------

MATRIX_COLUMNS = [
    "pitcher_group", "batter_group", "n_pa",
    "k_rate_raw", "k_rate_shrunk", "global_rate",
]

# Column the lookup prefers as the matchup point estimate (shrunk toward the global
# rate by the matrix builder). We fall back to raw, then global, then a passed value.
_RATE_COL = "k_rate_shrunk"


def global_rate_of(matrix: pd.DataFrame) -> float:
    """The league-wide K/PA stored on the matrix (every row carries the same value).

    Robust to an empty matrix (returns NaN) so callers can decide the fallback.
    """
    if matrix is None or len(matrix) == 0 or "global_rate" not in matrix.columns:
        return float("nan")
    return float(pd.to_numeric(matrix["global_rate"], errors="coerce").dropna().iloc[0])


def matchup_k_rate(
    matrix: pd.DataFrame,
    pgroup,
    bgroup,
    *,
    default: Optional[float] = None,
) -> float:
    """Look up the K/PA for a (pitcher_group, batter_group) cell.

    Returns the shrunk rate when present, else the raw rate, else the matrix global
    rate, else ``default`` (or NaN). A missing/None group, or a cell that simply has
    no data, falls through to the global rate — this is the documented fallback the
    prior relies on when a player's group is unknown.
    """
    if matrix is None or len(matrix) == 0:
        return default if default is not None else float("nan")

    glob = global_rate_of(matrix)
    fallback = glob if not np.isnan(glob) else (default if default is not None else float("nan"))

    if pgroup is None or bgroup is None or (isinstance(pgroup, float) and np.isnan(pgroup)):
        return fallback

    cell = matrix[(matrix["pitcher_group"] == pgroup) & (matrix["batter_group"] == bgroup)]
    if len(cell) == 0:
        return fallback

    row = cell.iloc[0]
    for col in (_RATE_COL, "k_rate_raw", "global_rate"):
        if col in row.index:
            val = pd.to_numeric(pd.Series([row[col]]), errors="coerce").iloc[0]
            if val is not None and not pd.isna(val):
                return float(val)
    return fallback


# ---------------------------------------------------------------------------
# Group assignment helper
# ---------------------------------------------------------------------------

def player_group(groups_df: pd.DataFrame, player_id, season: int):
    """Return the cluster GROUP for ``player_id`` in ``season`` (or None if unknown).

    ``groups_df`` is a {pitcher,batter}_groups.parquet table with columns
    (player_id, season, group). The join is exact on both keys; a player with no row
    for that season returns None so callers fall back to the global rate.
    """
    if groups_df is None or len(groups_df) == 0:
        return None
    hit = groups_df[
        (groups_df["player_id"] == player_id) & (groups_df["season"] == season)
    ]
    if len(hit) == 0:
        return None
    return hit.iloc[0]["group"]


# ---------------------------------------------------------------------------
# TASK A — the prior (PURE math, unit-testable)
# ---------------------------------------------------------------------------

def expected_ks_prior(
    pitcher_group,
    batter_lineup_groups: Sequence,
    expected_bf: float,
    matrix: pd.DataFrame,
    *,
    lookup: Optional[Callable] = None,
    scale_to_bf: bool = True,
) -> float:
    """Prior expected strikeouts (lambda) for a start, from the group-vs-group matrix.

    Formula
    -------
    Let the pitcher's group be ``g_p`` and ``L = [g_b1 ... g_bk]`` the ordered list of
    batter groups he is scheduled to face (a 9-man lineup, repeated as the order turns
    over). With ``r(g_p, g_b) = matchup_k_rate(matrix, g_p, g_b)`` the per-PA K rate:

        mean_rate = (1 / |L|) * sum_{g_b in L} r(g_p, g_b)
        lambda    = mean_rate * expected_bf            (scale_to_bf=True, default)

    The mean*BF form is robust to ``expected_bf`` and ``|L|`` disagreeing (BF is a
    projection; the lineup list is whoever we listed). If you instead pass the EXACT
    batters faced as ``batter_lineup_groups`` and set ``scale_to_bf=False``, lambda is
    the plain sum of per-PA rates over those PAs:

        lambda = sum_{g_b in L} r(g_p, g_b)

    Fallback
    --------
    A missing pitcher group, missing batter group, or an empty lineup degrades to
    ``global_rate * expected_bf`` — never an error, never a silent zero. ``matchup_k_rate``
    already substitutes the global rate per-cell, so per-batter fallback is automatic;
    the explicit global path here covers the empty-lineup / empty-matrix cases.

    Parameters
    ----------
    lookup : optional callable ``(matrix, pgroup, bgroup) -> rate``. Defaults to this
        module's ``matchup_k_rate``. Pass the parallel task's lookup to use it instead;
        the math is identical.
    """
    look = lookup or matchup_k_rate
    glob = global_rate_of(matrix)

    groups = list(batter_lineup_groups) if batter_lineup_groups is not None else []
    if len(groups) == 0:
        # No lineup info at all -> pure global fallback.
        base = glob if not np.isnan(glob) else 0.0
        return float(base * expected_bf)

    rates = [look(matrix, pitcher_group, bg) for bg in groups]
    rates = [r for r in rates if r is not None and not (isinstance(r, float) and np.isnan(r))]
    if not rates:
        base = glob if not np.isnan(glob) else 0.0
        return float(base * expected_bf)

    if scale_to_bf:
        mean_rate = float(np.mean(rates))
        return float(mean_rate * expected_bf)
    return float(np.sum(rates))


# ---------------------------------------------------------------------------
# PURE scoring helpers (unit-testable; no I/O)
# ---------------------------------------------------------------------------

def mae(predicted: Sequence[float], actual: Sequence[float]) -> float:
    """Mean absolute error. Raises on length mismatch or empty input."""
    p = np.asarray(predicted, dtype="float64")
    a = np.asarray(actual, dtype="float64")
    if p.shape != a.shape:
        raise ValueError(f"length mismatch: {p.shape} vs {a.shape}")
    if p.size == 0:
        raise ValueError("cannot score empty arrays")
    return float(np.mean(np.abs(p - a)))


@dataclass(frozen=True)
class OOSResult:
    """Structured OOS score. ``improvement`` > 0 means the prior beat the baseline."""
    n: int
    prior_mae: float
    baseline_mae: float
    improvement: float          # baseline_mae - prior_mae  (positive = prior better)
    beats_baseline: bool

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "prior_mae": self.prior_mae,
            "baseline_mae": self.baseline_mae,
            "improvement": self.improvement,
            "beats_baseline": self.beats_baseline,
        }


def score_predictions(
    prior_pred: Sequence[float],
    baseline_pred: Sequence[float],
    actual: Sequence[float],
) -> OOSResult:
    """Compare prior vs baseline predictions against actuals. Pure math.

    ``improvement = baseline_mae - prior_mae`` (positive means the group prior is
    better out of sample). ``beats_baseline`` is the production gate.
    """
    prior_mae = mae(prior_pred, actual)
    baseline_mae = mae(baseline_pred, actual)
    improvement = baseline_mae - prior_mae
    return OOSResult(
        n=len(actual),
        prior_mae=prior_mae,
        baseline_mae=baseline_mae,
        improvement=improvement,
        beats_baseline=improvement > 0,
    )


# ---------------------------------------------------------------------------
# TASK B — OOS validation harness (heavy I/O, kept separate from scoring math)
# ---------------------------------------------------------------------------

# Where the parallel matrix task writes its outputs (override via STRIKE_DATA_DIR).
def matrix_path(data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / "groups" / "matchup_matrix.parquet"


def groups_path(role: str, data_dir: Path = DATA_DIR) -> Path:
    """``role`` is 'pitcher' or 'batter'."""
    return Path(data_dir) / "groups" / f"{role}_groups.parquet"


def load_matrix(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Load the group-vs-group matrix Parquet (raises if not built yet)."""
    path = matrix_path(data_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"matchup matrix not found at {path} — build it from TRAIN years first "
            "(parallel task: matchup_matrix.parquet)."
        )
    return pd.read_parquet(path)


def load_groups(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load (pitcher_groups, batter_groups). Raises if either is missing."""
    pit_p, bat_p = groups_path("pitcher", data_dir), groups_path("batter", data_dir)
    if not pit_p.exists() or not bat_p.exists():
        raise FileNotFoundError(f"group mappings not found at {pit_p} / {bat_p}")
    return pd.read_parquet(pit_p), pd.read_parquet(bat_p)


# Retrosheet columns we need to reconstruct per-start (pitcher, season) actuals and
# the lineup of batters faced. ``gid`` encodes the date/season; ``batter`` order
# within a game approximates the lineup the starter saw.
_START_USECOLS = ["gid", "pitcher", "batter", "pa", "k"]


def _season_from_gid(gid: pd.Series) -> pd.Series:
    """Retrosheet gid is e.g. 'ANA201504100' -> season = chars 3..7."""
    return pd.to_numeric(gid.astype(str).str.slice(3, 7), errors="coerce").astype("Int64")


def load_test_starts(
    test_years: Iterable[int],
    data_dir: Path = DATA_DIR,
    *,
    min_bf: int = 10,
) -> pd.DataFrame:
    """Reconstruct per-(game, starting pitcher) rows from Retrosheet TEST seasons.

    A "start" here is one (gid, pitcher) group: the BF (sum of PA the pitcher faced
    that game), the ACTUAL Ks that game, and the ordered list of batter ids faced
    (used to look up batter groups). We approximate the STARTER as the pitcher who
    faced the most batters in the game (relievers face far fewer), and keep only
    games where that pitcher faced >= ``min_bf`` batters.

    Returns columns: gid, season, pitcher, bf, actual_k, batters (list of ids).
    """
    frames = []
    for year in test_years:
        path = plays_path(year, data_dir)
        if not path.exists():
            continue
        df = pd.read_csv(path, usecols=_START_USECOLS, low_memory=False)
        df["pa"] = pd.to_numeric(df["pa"], errors="coerce").fillna(0)
        df["k"] = pd.to_numeric(df["k"], errors="coerce").fillna(0)
        df["season"] = _season_from_gid(df["gid"])

        grp = df.groupby(["gid", "pitcher"], sort=False)
        agg = grp.agg(
            season=("season", "first"),
            bf=("pa", "sum"),
            actual_k=("k", "sum"),
            batters=("batter", list),
        ).reset_index()
        # Keep the starter (max BF) per game.
        agg = agg.sort_values("bf", ascending=False).drop_duplicates("gid", keep="first")
        agg = agg[agg["bf"] >= min_bf]
        frames.append(agg)

    if not frames:
        return pd.DataFrame(columns=["gid", "season", "pitcher", "bf", "actual_k", "batters"])
    return pd.concat(frames, ignore_index=True)


def _predict_start(
    row: pd.Series,
    matrix: pd.DataFrame,
    pitcher_groups: pd.DataFrame,
    batter_groups: pd.DataFrame,
) -> tuple[float, float]:
    """Return (prior_pred, baseline_pred) for one start row.

    prior     : group-vs-group expected Ks (this module's prior).
    baseline  : league global K/PA * BF — the naive bar the prior must beat.
    """
    season = int(row["season"])
    bf = float(row["bf"])
    glob = global_rate_of(matrix)
    baseline = (glob if not np.isnan(glob) else 0.0) * bf

    pg = player_group(pitcher_groups, row["pitcher"], season)
    bgroups = [player_group(batter_groups, b, season) for b in row["batters"]]
    prior = expected_ks_prior(pg, bgroups, bf, matrix, scale_to_bf=True)
    return prior, baseline


def evaluate_prior_oos(
    train_years: Iterable[int],
    test_years: Iterable[int],
    data_dir: Path = DATA_DIR,
    *,
    matrix: Optional[pd.DataFrame] = None,
    min_bf: int = 10,
) -> dict:
    """OUT-OF-SAMPLE gate: does the group prior beat a naive baseline on TEST starts?

    The matrix MUST be built from TRAIN years only (no leakage). We either accept a
    pre-built ``matrix`` (already trained on ``train_years``) or load the on-disk
    matchup_matrix.parquet — which the parallel task is responsible for producing
    from TRAIN years. ``train_years`` is recorded in the result and used by the
    docstring/contract; this harness does not silently retrain on test data.

    For each TEST start we predict prior Ks and baseline Ks (global_rate * BF) and
    score both against ACTUAL Ks. Returns ``OOSResult.as_dict()``.

    Raises FileNotFoundError if the matrix/groups are not built yet — the caller is
    expected to handle that ("not present, ran synthetic tests instead").
    """
    if matrix is None:
        matrix = load_matrix(data_dir)
    pitcher_groups, batter_groups = load_groups(data_dir)

    starts = load_test_starts(test_years, data_dir, min_bf=min_bf)
    if len(starts) == 0:
        raise FileNotFoundError(
            f"no Retrosheet plays found for TEST years {list(test_years)} under {data_dir}"
        )

    prior_pred, baseline_pred, actual = [], [], []
    for _, row in starts.iterrows():
        p, b = _predict_start(row, matrix, pitcher_groups, batter_groups)
        prior_pred.append(p)
        baseline_pred.append(b)
        actual.append(float(row["actual_k"]))

    result = score_predictions(prior_pred, baseline_pred, actual)
    out = result.as_dict()
    out["train_years"] = list(train_years)
    out["test_years"] = list(test_years)
    return out
