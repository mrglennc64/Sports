"""Tests for Retrosheet feature aggregation (pure pandas, no file I/O)."""
from __future__ import annotations

import pandas as pd

from app.grouping.features import FEATURE_COLUMNS, _aggregate, _prep_rows


def _row(**kw):
    base = dict(gid="g", batter="B", pitcher="P1", bathand="R", pithand="R",
                balls=0, strikes=0, pitches="", nump=0, pa=1, k=0, walk=0,
                bip=0, ground=0, fly=0, line=0)
    base.update(kw)
    return base


def test_aggregation_matches_hand_computed_rates():
    df = pd.DataFrame([
        # PA1: called + 2 swinging strikes, K, vs LHB, reached 2 strikes
        _row(batter="b1", bathand="L", pitches="CSS", nump=3, strikes=2, k=1),
        # PA2: 2 balls then ball in play (groundball), vs RHB, no K
        _row(batter="b2", bathand="R", pitches="BBX", nump=3, strikes=0, k=0,
             bip=1, ground=1),
    ])
    feats = _aggregate(_prep_rows(df), "pitcher")
    r = feats.iloc[0]
    assert r["pa"] == 2
    assert r["k_rate"] == 0.5
    assert round(r["swstr_rate"], 3) == round(2 / 6, 3)      # 2 swinging of 6 pitches
    assert round(r["called_strike_rate"], 3) == round(1 / 6, 3)
    assert r["gb_rate"] == 1.0                                # 1 of 1 ball in play
    assert r["put_away_rate"] == 1.0                          # 1 K of 1 two-strike PA
    assert r["k_rate_vs_L"] == 1.0                            # the LHB PA was a K
    assert r["k_rate_vs_R"] == 0.0
    assert r["first_pitch_strike_rate"] == 0.5               # PA1 'C' yes, PA2 'B' no
    assert round(r["pitches_per_pa"], 2) == 3.0


def test_feature_columns_are_all_produced():
    df = pd.DataFrame([_row(pitches="CX", nump=2, bip=1, fly=1)])
    feats = _aggregate(_prep_rows(df), "pitcher")
    for col in FEATURE_COLUMNS:
        assert col in feats.columns
