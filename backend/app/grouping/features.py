"""Feature engineering from Retrosheet play-by-play (per pitcher / batter / season).

Turns ``{year}plays.csv`` into behavioural feature vectors we later cluster into
GROUPS. Every feature is derived from columns verified to exist in the real file —
no Statcast metrics here (those come from app.grouping.statcast and are joined in
Phase 2).

Pitch-result string (``pitches``) codes we rely on (Retrosheet spec):
  S, M, Q  -> swinging strike / whiff (bat missed)
  C        -> called strike
  others (B/F/X/...) counted via the season's ``nump`` (pitch count) totals.

The unit is a (player, season) row with the underlying PA count kept, so downstream
clustering can filter thin samples and/or pool seasons. Pure-pandas; offline only.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.grouping.retrosheet import DATA_DIR, plays_path

# Columns we actually read (keeps a ~195k-row season light in memory).
_USECOLS = [
    "gid", "batter", "pitcher", "bathand", "pithand",
    "balls", "strikes", "pitches", "nump",
    "pa", "k", "walk", "bip", "ground", "fly", "line",
]

# A whiff = the batter swung and missed. Retrosheet: S (swinging), M (missed bunt),
# Q (swung on pitchout).
_WHIFF_CODES = ("S", "M", "Q")

# Minimum PAs for a (player, season) row to be worth clustering (thin samples are
# noise; the whole point of groups is statistical significance).
MIN_PA = 50


def _prep_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-PA indicator columns used by the group-bys (vectorized)."""
    p = df["pitches"].fillna("").astype(str)
    df = df.assign(
        n_whiff=sum(p.str.count(c) for c in _WHIFF_CODES),
        n_called=p.str.count("C"),
        npitch=pd.to_numeric(df["nump"], errors="coerce").fillna(p.str.len()),
        # reached two strikes (Retrosheet caps the strikes field at 2)
        two_strk=(pd.to_numeric(df["strikes"], errors="coerce") == 2).astype(int),
        # first pitch was a strike / in play (anything that isn't a ball-type first char)
        fp_strike=p.str.slice(0, 1).isin(list("CSFTLOXYKMQR")).astype(int),
        is_l=(df["bathand"].astype(str) == "L").astype(int),
        is_r=(df["bathand"].astype(str) == "R").astype(int),
    )
    for col in ("k", "pa", "bip", "ground", "fly", "line", "walk"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["two_strk_k"] = ((df["two_strk"] == 1) & (df["k"] == 1)).astype(int)
    df["k_l"] = df["k"] * df["is_l"]
    df["k_r"] = df["k"] * df["is_r"]
    df["pa_l"] = df["pa"] * df["is_l"]
    df["pa_r"] = df["pa"] * df["is_r"]
    return df


def _aggregate(df: pd.DataFrame, key: str) -> pd.DataFrame:
    g = df.groupby(key).agg(
        pa=("pa", "sum"), k=("k", "sum"), walk=("walk", "sum"),
        bip=("bip", "sum"), ground=("ground", "sum"), fly=("fly", "sum"), line=("line", "sum"),
        npitch=("npitch", "sum"), n_whiff=("n_whiff", "sum"), n_called=("n_called", "sum"),
        fp_strike=("fp_strike", "sum"), two_strk=("two_strk", "sum"), two_strk_k=("two_strk_k", "sum"),
        k_l=("k_l", "sum"), k_r=("k_r", "sum"), pa_l=("pa_l", "sum"), pa_r=("pa_r", "sum"),
    ).reset_index().rename(columns={key: "player_id"})

    pa = g["pa"].replace(0, pd.NA)
    bip = g["bip"].replace(0, pd.NA)
    npitch = g["npitch"].replace(0, pd.NA)
    feats = pd.DataFrame({
        "player_id": g["player_id"],
        "pa": g["pa"],
        "k_rate": g["k"] / pa,
        "bb_rate": g["walk"] / pa,
        "gb_rate": g["ground"] / bip,
        "fb_rate": g["fly"] / bip,
        "ld_rate": g["line"] / bip,
        "swstr_rate": g["n_whiff"] / npitch,
        "called_strike_rate": g["n_called"] / npitch,
        "first_pitch_strike_rate": g["fp_strike"] / pa,
        "put_away_rate": g["two_strk_k"] / g["two_strk"].replace(0, pd.NA),
        "k_rate_vs_L": g["k_l"] / g["pa_l"].replace(0, pd.NA),
        "k_rate_vs_R": g["k_r"] / g["pa_r"].replace(0, pd.NA),
        "pitches_per_pa": g["npitch"] / pa,
    })
    return feats


FEATURE_COLUMNS = [
    "k_rate", "bb_rate", "gb_rate", "fb_rate", "ld_rate",
    "swstr_rate", "called_strike_rate", "first_pitch_strike_rate",
    "put_away_rate", "k_rate_vs_L", "k_rate_vs_R", "pitches_per_pa",
]


def season_features(year: int, data_dir: Path = DATA_DIR, min_pa: int = MIN_PA):
    """Return (pitchers_df, batters_df) of per-player feature rows for one season."""
    df = pd.read_csv(plays_path(year, data_dir), usecols=_USECOLS, low_memory=False)
    df = _prep_rows(df)
    pit = _aggregate(df, "pitcher")
    bat = _aggregate(df, "batter")
    pit, bat = (x[x["pa"] >= min_pa].copy() for x in (pit, bat))
    pit["season"], bat["season"] = year, year
    pit["role"], bat["role"] = "pitcher", "batter"
    return pit, bat


def build_features(years, data_dir: Path = DATA_DIR, min_pa: int = MIN_PA):
    """Concatenate per-season features across years. Returns (pitchers, batters)."""
    pits, bats = [], []
    for year in years:
        p, b = season_features(year, data_dir, min_pa)
        print(f"[features] {year}: {len(p)} pitchers, {len(b)} batters (>= {min_pa} PA)")
        pits.append(p)
        bats.append(b)
    return (pd.concat(pits, ignore_index=True), pd.concat(bats, ignore_index=True))


def write_features(years, data_dir: Path = DATA_DIR, min_pa: int = MIN_PA) -> dict:
    """Build and persist feature tables to Parquet under <data_dir>/features/."""
    pit, bat = build_features(years, data_dir, min_pa)
    out = Path(data_dir) / "features"
    out.mkdir(parents=True, exist_ok=True)
    pit_path, bat_path = out / "pitchers.parquet", out / "batters.parquet"
    pit.to_parquet(pit_path, index=False)
    bat.to_parquet(bat_path, index=False)
    return {"pitchers": str(pit_path), "batters": str(bat_path),
            "n_pitchers": len(pit), "n_batters": len(bat)}
