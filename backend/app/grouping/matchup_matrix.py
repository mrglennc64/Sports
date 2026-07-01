"""Group-vs-group strikeout baseline matrix (offline).

Answers: *when a pitcher in group P faces a batter in group B, what is the
expected strikeout rate, over ~10 years of real plate appearances?*

Pipeline:
  1. For each season, stream ``{year}plays.csv`` (only pitcher/batter/pa/k cols).
  2. Join each play's pitcher -> pitcher_group and batter -> batter_group using the
     per-season group mappings (matched by player id + that same season).
  3. Keep only real PAs (``pa == 1``).
  4. Aggregate per (pitcher_group, batter_group): n_pa, k_sum, raw k-rate.
  5. Empirical-Bayes shrink each cell toward the GLOBAL k-rate so thin cells are
     not trusted blindly:
         k_rate_shrunk = (k_sum + m * global_rate) / (n_pa + m)
     ``m`` is a pseudo-count (PAs of "prior" pulling toward the mean). Big cells
     swamp ``m`` and stay near raw; tiny cells get pulled to the global mean.

Output parquet: C:\\strike-data\\groups\\matchup_matrix.parquet with columns
  [pitcher_group, batter_group, n_pa, k_sum, k_rate_raw, k_rate_shrunk, global_rate]

The core aggregation (``aggregate_matchups``) works on an in-memory plays
DataFrame so it is unit-testable without any files; ``build_matchup_matrix`` is
the thin file-streaming wrapper that calls it per season.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from app.grouping.retrosheet import DATA_DIR

# Default pseudo-count (in PAs) for empirical-Bayes shrinkage. A cell with this
# many PAs sits exactly halfway between its raw rate and the global rate.
DEFAULT_M = 200.0

GROUPS_DIR = Path(DATA_DIR) / "groups"

# Only these columns are read from each (large) plays.csv.
_USECOLS = ["pitcher", "batter", "pa", "k"]


# --------------------------------------------------------------------------- #
# Group-mapping helpers
# --------------------------------------------------------------------------- #
def load_group_map(path: str | Path) -> pd.DataFrame:
    """Load a {pitcher,batter}_groups.parquet -> [player_id, season, group].

    Keeps only the join keys (player id + season) and the integer group. Any
    extra profiling columns from the clustering step are dropped.
    """
    df = pd.read_parquet(path, columns=None)
    missing = {"player_id", "season", "group"} - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    out = df[["player_id", "season", "group"]].copy()
    out["season"] = out["season"].astype(int)
    out["group"] = out["group"].astype(int)
    return out


def _join_groups(
    plays: pd.DataFrame,
    season: int,
    pitcher_groups: pd.DataFrame,
    batter_groups: pd.DataFrame,
) -> pd.DataFrame:
    """Attach pitcher_group / batter_group to a single season's plays.

    Group mappings are filtered to ``season`` first, then joined by player id, so
    the same player can sit in different groups in different years.
    """
    pg = (
        pitcher_groups.loc[pitcher_groups["season"] == season, ["player_id", "group"]]
        .rename(columns={"player_id": "pitcher", "group": "pitcher_group"})
    )
    bg = (
        batter_groups.loc[batter_groups["season"] == season, ["player_id", "group"]]
        .rename(columns={"player_id": "batter", "group": "batter_group"})
    )
    out = plays.merge(pg, on="pitcher", how="inner").merge(bg, on="batter", how="inner")
    return out


# --------------------------------------------------------------------------- #
# Core aggregation (pure, in-memory, testable)
# --------------------------------------------------------------------------- #
def aggregate_matchups(
    plays: pd.DataFrame,
    pitcher_groups: pd.DataFrame,
    batter_groups: pd.DataFrame,
    *,
    season_col: str = "season",
    m: float = DEFAULT_M,
) -> pd.DataFrame:
    """Build the group-vs-group K matrix from an in-memory plays DataFrame.

    ``plays`` must have columns: pitcher, batter, pa, k, and a season column
    (default ``season``). Group mappings have [player_id, season, group].

    Returns one row per (pitcher_group, batter_group) seen in the data with
    columns [pitcher_group, batter_group, n_pa, k_sum, k_rate_raw,
    k_rate_shrunk, global_rate].
    """
    frames: list[pd.DataFrame] = []
    for season, season_plays in plays.groupby(season_col, sort=True):
        joined = _join_groups(
            season_plays[["pitcher", "batter", "pa", "k"]].copy(),
            int(season),
            pitcher_groups,
            batter_groups,
        )
        if not joined.empty:
            frames.append(joined)

    cols = [
        "pitcher_group", "batter_group", "n_pa", "k_sum",
        "k_rate_raw", "k_rate_shrunk", "global_rate",
    ]
    if not frames:
        return pd.DataFrame(columns=cols)

    joined_all = pd.concat(frames, ignore_index=True)
    # Keep only real plate appearances.
    joined_all = joined_all[joined_all["pa"] == 1]
    if joined_all.empty:
        return pd.DataFrame(columns=cols)

    return _aggregate_joined(joined_all, m=m)


def _aggregate_joined(joined: pd.DataFrame, *, m: float) -> pd.DataFrame:
    """Group already-joined PA rows into the per-cell shrunk matrix."""
    grp = (
        joined.groupby(["pitcher_group", "batter_group"], as_index=False)
        .agg(n_pa=("pa", "sum"), k_sum=("k", "sum"))
    )
    grp["n_pa"] = grp["n_pa"].astype(int)
    grp["k_sum"] = grp["k_sum"].astype(int)

    total_pa = int(grp["n_pa"].sum())
    total_k = int(grp["k_sum"].sum())
    global_rate = total_k / total_pa if total_pa else 0.0

    grp["k_rate_raw"] = grp["k_sum"] / grp["n_pa"]
    grp["k_rate_shrunk"] = (grp["k_sum"] + m * global_rate) / (grp["n_pa"] + m)
    grp["global_rate"] = global_rate

    cols = [
        "pitcher_group", "batter_group", "n_pa", "k_sum",
        "k_rate_raw", "k_rate_shrunk", "global_rate",
    ]
    return grp[cols].sort_values(["pitcher_group", "batter_group"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# File-streaming wrapper
# --------------------------------------------------------------------------- #
def _plays_csv_path(year: int, data_dir: str | Path) -> Path:
    return Path(data_dir) / "retrosheet" / str(year) / f"{year}plays.csv"


def build_matchup_matrix(
    years: Iterable[int],
    groups_dir: str | Path = GROUPS_DIR,
    data_dir: str | Path = DATA_DIR,
    *,
    m: float = DEFAULT_M,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    """Stream every season's plays.csv, build the K matrix, and write parquet.

    ``years`` are the season folders to read. The folder year is used as the
    season for the group join. Writes ``<groups_dir>/matchup_matrix.parquet``
    (unless ``out_path`` overrides) and returns the matrix DataFrame.
    """
    groups_dir = Path(groups_dir)
    pitcher_groups = load_group_map(groups_dir / "pitcher_groups.parquet")
    batter_groups = load_group_map(groups_dir / "batter_groups.parquet")

    joined_frames: list[pd.DataFrame] = []
    for year in years:
        csv_path = _plays_csv_path(year, data_dir)
        if not csv_path.exists():
            continue
        plays = pd.read_csv(csv_path, usecols=_USECOLS)
        plays = plays[plays["pa"] == 1]
        if plays.empty:
            continue
        joined = _join_groups(plays, int(year), pitcher_groups, batter_groups)
        if not joined.empty:
            joined_frames.append(joined)

    cols = [
        "pitcher_group", "batter_group", "n_pa", "k_sum",
        "k_rate_raw", "k_rate_shrunk", "global_rate",
    ]
    if not joined_frames:
        matrix = pd.DataFrame(columns=cols)
    else:
        matrix = _aggregate_joined(pd.concat(joined_frames, ignore_index=True), m=m)

    out = Path(out_path) if out_path is not None else groups_dir / "matchup_matrix.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_parquet(out, index=False)
    return matrix


# --------------------------------------------------------------------------- #
# Consumers
# --------------------------------------------------------------------------- #
def to_pivot(matrix: pd.DataFrame) -> pd.DataFrame:
    """pitcher_group (rows) x batter_group (cols) table of k_rate_shrunk."""
    return matrix.pivot(
        index="pitcher_group", columns="batter_group", values="k_rate_shrunk"
    )


def matchup_k_rate(matrix: pd.DataFrame, pgroup: int, bgroup: int) -> float:
    """Shrunk K-rate for (pgroup, bgroup), falling back to the global rate.

    Unseen cells return ``global_rate`` (the matrix-wide mean), which is the
    most defensible prior when a specific group pairing was never observed.
    """
    hit = matrix[
        (matrix["pitcher_group"] == pgroup) & (matrix["batter_group"] == bgroup)
    ]
    if not hit.empty:
        return float(hit["k_rate_shrunk"].iloc[0])
    if matrix.empty or "global_rate" not in matrix.columns:
        return 0.0
    return float(matrix["global_rate"].iloc[0])
