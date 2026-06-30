"""Statcast / Baseball Savant pull — the pitch-physics layer Retrosheet lacks.

Retrosheet gives event outcomes + pitch-RESULT strings, but no pitch TYPES, no
velocity, no batted-ball physics. Statcast (2015+, via pybaseball) fills that gap:
pitch type, release speed, exit velocity, launch angle, and the swing/whiff
description per pitch. We pull a season, then aggregate per pitcher/batter into the
features that complement (and join to) the Retrosheet ones in Phase 2.

Heads up: a full season is ~700k pitches and the Savant pull is rate-limited — a
10-year pull is a long batch job (run ``pull_season`` per year, cached to Parquet),
not a quick call. ``pybaseball`` is an OFFLINE dependency (requirements-grouping.txt),
never installed on the production server.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.grouping.retrosheet import DATA_DIR

# Pitch-type buckets (Statcast pitch_type codes).
_FASTBALL = {"FF", "FA", "FT", "SI", "FC"}
_BREAKING = {"SL", "ST", "CU", "KC", "CS", "SV", "KN", "SC"}
_OFFSPEED = {"CH", "FS", "FO", "EP"}

_WHIFF_DESC = {"swinging_strike", "swinging_strike_blocked"}
_SWING_DESC = _WHIFF_DESC | {"foul", "foul_tip", "hit_into_play",
                            "hit_into_play_score", "hit_into_play_no_out"}
# Statcast zone: 1-9 in the strike zone, 11-14 outside.
_OUT_OF_ZONE = {11, 12, 13, 14}


def pitch_bucket(pitch_type: str) -> str:
    if pitch_type in _FASTBALL:
        return "fastball"
    if pitch_type in _BREAKING:
        return "breaking"
    if pitch_type in _OFFSPEED:
        return "offspeed"
    return "other"


def statcast_dir(data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / "statcast"


def pull_season(year: int, data_dir: Path = DATA_DIR, *, force: bool = False) -> Path:
    """Pull one season of Statcast pitches to Parquet (cached). Returns the path.

    Imports pybaseball lazily so the module loads even where it isn't installed.
    """
    out_dir = statcast_dir(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{year}_statcast.parquet"
    if path.exists() and not force:
        return path
    from pybaseball import statcast  # lazy: offline-only dependency

    df = statcast(start_dt=f"{year}-03-01", end_dt=f"{year}-11-30")
    df.to_parquet(path, index=False)
    return path


def _flags(df: pd.DataFrame) -> pd.DataFrame:
    desc = df["description"].astype(str)
    # Statcast ships zone/launch_speed/... as nullable arrays; coerce to float64 and
    # fillna(False) before any astype(int) so NA never reaches the integer cast.
    zone = pd.to_numeric(df.get("zone"), errors="coerce").astype("float64")
    ev = pd.to_numeric(df.get("launch_speed"), errors="coerce").astype("float64")
    df = df.assign(
        bucket=df["pitch_type"].astype(str).map(pitch_bucket),
        is_whiff=desc.isin(_WHIFF_DESC).astype(int),
        is_swing=desc.isin(_SWING_DESC).astype(int),
        out_of_zone=zone.isin(_OUT_OF_ZONE).fillna(False).astype(int),
        ev=ev,
        la=pd.to_numeric(df.get("launch_angle"), errors="coerce").astype("float64"),
        velo=pd.to_numeric(df.get("release_speed"), errors="coerce").astype("float64"),
        inplay=desc.str.startswith("hit_into_play").astype(int),
    )
    df["hard_hit"] = (df["ev"] >= 95).fillna(False).astype(int)
    df["chase"] = ((df["out_of_zone"] == 1) & (df["is_swing"] == 1)).astype(int)
    return df


def _whiff_by_bucket(g: pd.DataFrame, bucket: str) -> float:
    sub = g[g["bucket"] == bucket]
    sw = sub["is_swing"].sum()
    return (sub["is_whiff"].sum() / sw) if sw else float("nan")


def aggregate_features(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Per-player Statcast features. ``key`` is 'pitcher' or 'batter' (the id column)."""
    df = _flags(df)
    rows = []
    for pid, g in df.groupby(key):
        n = len(g)
        bip = g[g["inplay"] == 1]
        oz = g[g["out_of_zone"] == 1]
        rows.append({
            "player_id": pid,
            "pitches": n,
            "fastball_pct": (g["bucket"] == "fastball").mean(),
            "breaking_pct": (g["bucket"] == "breaking").mean(),
            "offspeed_pct": (g["bucket"] == "offspeed").mean(),
            "whiff_rate": g["is_whiff"].sum() / max(g["is_swing"].sum(), 1),
            "whiff_rate_fastball": _whiff_by_bucket(g, "fastball"),
            "whiff_rate_breaking": _whiff_by_bucket(g, "breaking"),
            "whiff_rate_offspeed": _whiff_by_bucket(g, "offspeed"),
            "chase_rate": (oz["is_swing"].mean() if len(oz) else float("nan")),
            "avg_fastball_velo": g.loc[g["bucket"] == "fastball", "velo"].mean(),
            "avg_exit_velo": bip["ev"].mean(),
            "avg_launch_angle": bip["la"].mean(),
            "hard_hit_rate": (bip["hard_hit"].mean() if len(bip) else float("nan")),
        })
    return pd.DataFrame(rows)


STATCAST_FEATURE_COLUMNS = [
    "fastball_pct", "breaking_pct", "offspeed_pct", "whiff_rate",
    "whiff_rate_fastball", "whiff_rate_breaking", "whiff_rate_offspeed",
    "chase_rate", "avg_fastball_velo", "avg_exit_velo", "avg_launch_angle", "hard_hit_rate",
]
