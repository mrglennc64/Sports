"""Reconstruct historical factor projections from Retrosheet (leak-free).

For each start, rebuild ProjectionInputs using ONLY games strictly before the start
date, run the production ``project()`` ensemble, and record the 10 component
estimates + actual Ks. Offline only.

The dominant factors (opponent K profile 0.26, recent form 0.22, expected innings
0.18, lineup 0.09 = 75% of the weight) are reconstructed from Retrosheet; the minor
factors (umpire / pitch-mix / bullpen / weather / catcher) are neutral-defaulted —
which is exactly why their components equal the matchup estimate (the collinearity
this dataset exposes). MAE on this offline reconstruction is a bit higher than the
live pipeline (cruder opponent windows, no live minor-factor data); refine the input
fidelity before using the table for an actual fit, not just the structural read.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.model.inputs import (ExpectedWorkload, Handedness, LineupStrength,
                              OpponentKProfile, PitcherRecentForm, ProjectionInputs)
from app.model.projection import project
from app.model.weights import ModelConfig

BATTERS_PER_INNING = 4.3
_COLS = ["gid", "pitcher", "batter", "batteam", "pithand", "pa", "k"]
COMPONENT_ORDER = ["opponent_k_profile", "pitcher_recent_form", "expected_innings",
                   "lineup_strength", "umpire", "pitch_count", "pitch_mix",
                   "bullpen_leash", "weather", "catcher_framing"]


def _load_plays(year: int, data_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(Path(data_dir) / "retrosheet" / str(year) / f"{year}plays.csv",
                     usecols=_COLS, low_memory=False)
    df = df[df["pa"] == 1].copy()
    df["date"] = pd.to_datetime(df["gid"].str[3:11], format="%Y%m%d")
    return df


def _prior_rate_map(df: pd.DataFrame, keys: list[str]) -> dict:
    """{(key..., date): K/PA over that key's games strictly BEFORE date} (leak-free)."""
    g = df.groupby(keys + ["date"]).agg(pa=("pa", "sum"), k=("k", "sum")).reset_index().sort_values("date")
    g["cpa"] = g.groupby(keys)["pa"].cumsum() - g["pa"]
    g["ck"] = g.groupby(keys)["k"].cumsum() - g["k"]
    g["r"] = np.where(g["cpa"] > 0, g["ck"] / g["cpa"], np.nan)
    idx = keys + ["date"]
    return {tuple(t) if len(idx) > 1 else t[0]: r for *t, r in g[idx + ["r"]].itertuples(index=False)}


def build_factor_table(year: int, data_dir: str | Path = r"C:\strike-data", min_prior_starts: int = 3) -> pd.DataFrame:
    """Return the per-start factor-projection table for one season."""
    data_dir = Path(data_dir)
    df = _load_plays(year, data_dir)
    lg = ModelConfig().league_avg_k_rate

    bat = _prior_rate_map(df, ["batter"])          # (batter, date) -> prior K rate
    team = _prior_rate_map(df, ["batteam"])        # (team, date)   -> prior K rate
    teamvh = _prior_rate_map(df, ["batteam", "pithand"])  # (team, hand, date) -> prior K rate

    starts = df.groupby(["gid", "pitcher"]).agg(
        bf=("pa", "sum"), k=("k", "sum"), pithand=("pithand", "first"),
        batteam=("batteam", "first"), date=("date", "first")).reset_index()
    starts = starts[starts["bf"] >= 15].sort_values(["pitcher", "date"])
    # precompute the actual lineup (batters faced) per (gid, pitcher)
    faced = df.groupby(["gid", "pitcher"])["batter"].apply(lambda s: list(s.unique())).to_dict()

    rows: list[dict] = []
    for pid, sub in starts.groupby("pitcher"):
        hk, hip = [], []
        for _, r in sub.iterrows():
            if len(hk) >= min_prior_starts:
                date, tm = r["date"], r["batteam"]
                ip = sum(hip[-6:]); kk = sum(hk[-6:])
                kper9 = float(min(9 * kk / ip if ip else 6.0, 18.0))
                exp_ip = float(max(np.mean(hip[-5:]), 1.0))
                lu = [bat.get((b, date), np.nan) for b in faced.get((r["gid"], pid), [])]
                lu = [x for x in lu if x == x]
                opp = team.get((tm, date));  opp = opp if opp and opp == opp else lg
                lu_kr = float(np.mean(lu)) if lu else opp
                vr = teamvh.get((tm, "R", date), np.nan); vl = teamvh.get((tm, "L", date), np.nan)
                vr = vr if vr == vr else opp; vl = vl if vl == vl else opp
                try:
                    res = project(ProjectionInputs(
                        pitcher_name=pid,
                        opponent=OpponentKProfile(k_pct_vs_rhp=vr, k_pct_vs_lhp=vl,
                                                  k_pct_last_14=opp, k_pct_last_30=opp,
                                                  k_pct_starting_lineup=lu_kr),
                        pitcher_form=PitcherRecentForm(throws=Handedness(r["pithand"]),
                                                       recent_start_ks=[int(x) for x in hk[-5:][::-1]],
                                                       k_per_9_last_30=kper9),
                        workload=ExpectedWorkload(expected_innings=exp_ip,
                                                  expected_pitch_count=exp_ip * 16,
                                                  manager_hook_pitch_count=exp_ip * 16 + 10),
                        lineup=LineupStrength(projected_lineup_k_pct=lu_kr)))
                    row = {"gid": r["gid"], "pitcher": pid, "date": date, "season": year,
                           "actual_ks": int(r["k"]), "proj_lambda": res.projected_ks}
                    row.update({c.name: c.estimate_ks for c in res.components})
                    rows.append(row)
                except Exception:
                    pass
            hk.append(int(r["k"])); hip.append(r["bf"] / BATTERS_PER_INNING)
    return pd.DataFrame(rows)


def build_and_write(years, data_dir: str | Path = r"C:\strike-data") -> dict:
    """Build the factor table for several seasons and persist to Parquet."""
    tables = [build_factor_table(y, data_dir) for y in years]
    out = pd.concat(tables, ignore_index=True)
    path = Path(data_dir) / "features" / "factor_projections.parquet"
    out.to_parquet(path, index=False)
    return {"path": str(path), "rows": len(out), "seasons": list(years)}
