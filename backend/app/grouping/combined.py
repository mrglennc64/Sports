"""Combine Retrosheet behavioural features with Statcast pitch-physics features.

Retrosheet keys players by string id ('kersc001'); Statcast by MLBAM numeric id.
To cluster on BOTH feature families we need the crosswalk (Chadwick register:
key_retro <-> key_mlbam), then an inner join on (retro_id, season).

Result: a per-(player, season) row carrying the 12 Retrosheet features + the 12
Statcast features — the richer vector Phase 2.5 re-clusters on to see whether
sharper groups beat the pitcher's own rate by a non-marginal margin.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.grouping.features import FEATURE_COLUMNS
from app.grouping.retrosheet import DATA_DIR
from app.grouping.statcast import STATCAST_FEATURE_COLUMNS, aggregate_features, statcast_dir

COMBINED_FEATURE_COLUMNS = FEATURE_COLUMNS + STATCAST_FEATURE_COLUMNS


def mlbam_to_retro() -> dict[int, str]:
    """Map MLBAM numeric id -> Retrosheet string id via the Chadwick register (cached)."""
    from pybaseball import chadwick_register

    reg = chadwick_register().dropna(subset=["key_mlbam", "key_retro"])
    return {int(m): r for m, r in zip(reg["key_mlbam"], reg["key_retro"])}


def statcast_season_features(year: int, role: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Aggregate one season's Statcast pitches into per-player features (MLBAM-keyed)."""
    df = pd.read_parquet(statcast_dir(data_dir) / f"{year}_statcast.parquet")
    key = "pitcher" if role == "pitcher" else "batter"
    feats = aggregate_features(df, key)          # player_id = MLBAM id
    feats["season"] = year
    return feats


def build_combined(role: str, years, data_dir: Path = DATA_DIR, *, x2r: dict | None = None) -> pd.DataFrame:
    """Inner-join Retrosheet features with Statcast features on (retro_id, season)."""
    retro = pd.read_parquet(Path(data_dir) / "features" / f"{role}s.parquet")
    x2r = x2r if x2r is not None else mlbam_to_retro()

    frames = []
    for y in years:
        sf = statcast_season_features(y, role, data_dir)
        sf["retro_id"] = sf["player_id"].astype("Int64").map(lambda m: x2r.get(int(m)) if pd.notna(m) else None)
        frames.append(sf)
    sc = pd.concat(frames, ignore_index=True).dropna(subset=["retro_id"])

    combined = retro.merge(
        sc[["retro_id", "season"] + STATCAST_FEATURE_COLUMNS],
        left_on=["player_id", "season"], right_on=["retro_id", "season"], how="inner",
    ).drop(columns=["retro_id"])
    return combined


def write_combined(years, data_dir: Path = DATA_DIR) -> dict:
    """Build + persist combined feature tables for pitchers and batters."""
    out = Path(data_dir) / "features"
    x2r = mlbam_to_retro()
    res = {}
    for role in ("pitcher", "batter"):
        df = build_combined(role, years, data_dir, x2r=x2r)
        path = out / f"combined_{role}s.parquet"
        df.to_parquet(path, index=False)
        res[role] = {"path": str(path), "rows": len(df)}
    return res
