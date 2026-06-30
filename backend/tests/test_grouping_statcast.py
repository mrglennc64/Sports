"""Tests for Statcast feature aggregation (pure; no network/pybaseball)."""
from __future__ import annotations

import math

import pandas as pd

from app.grouping.statcast import aggregate_features, pitch_bucket


def test_pitch_bucket_classification():
    assert pitch_bucket("FF") == "fastball"
    assert pitch_bucket("SI") == "fastball"
    assert pitch_bucket("SL") == "breaking"
    assert pitch_bucket("CU") == "breaking"
    assert pitch_bucket("CH") == "offspeed"
    assert pitch_bucket("FS") == "offspeed"
    assert pitch_bucket("XX") == "other"


def test_aggregate_features_hand_computed():
    df = pd.DataFrame([
        # FB swinging strike (whiff) in zone
        {"pitcher": 1, "pitch_type": "FF", "description": "swinging_strike", "zone": 5,
         "launch_speed": None, "launch_angle": None, "release_speed": 95.0},
        # SL foul (swing, no whiff) out of zone -> a chase
        {"pitcher": 1, "pitch_type": "SL", "description": "foul", "zone": 12,
         "launch_speed": None, "launch_angle": None, "release_speed": 85.0},
        # FB hit into play, hard-hit
        {"pitcher": 1, "pitch_type": "FF", "description": "hit_into_play", "zone": 4,
         "launch_speed": 100.0, "launch_angle": 15.0, "release_speed": 96.0},
        # CH ball out of zone, no swing
        {"pitcher": 1, "pitch_type": "CH", "description": "ball", "zone": 13,
         "launch_speed": None, "launch_angle": None, "release_speed": 84.0},
    ])
    f = aggregate_features(df, "pitcher").iloc[0]
    assert f["pitches"] == 4
    assert f["fastball_pct"] == 0.5 and f["breaking_pct"] == 0.25 and f["offspeed_pct"] == 0.25
    assert math.isclose(f["whiff_rate"], 1 / 3, rel_tol=1e-6)       # 1 whiff of 3 swings
    assert f["whiff_rate_fastball"] == 0.5                          # 1 whiff of 2 FB swings
    assert f["chase_rate"] == 0.5                                   # 1 swing of 2 out-of-zone
    assert math.isclose(f["avg_fastball_velo"], 95.5, rel_tol=1e-6)  # (95+96)/2
    assert f["avg_exit_velo"] == 100.0 and f["hard_hit_rate"] == 1.0
