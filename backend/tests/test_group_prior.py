"""Unit tests for the group-vs-group strikeout prior + OOS scoring math.

All synthetic — no real Retrosheet/matrix files are touched. Verifies:
  * expected_ks_prior == hand-computed sum/mean*BF on a tiny matrix
  * global_rate fallback when groups are missing
  * matchup_k_rate cell lookup + fallback
  * MAE / improvement / gate computation on synthetic predicted-vs-actual arrays
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from app.grouping.group_prior import (
    OOSResult,
    expected_ks_prior,
    global_rate_of,
    mae,
    matchup_k_rate,
    player_group,
    score_predictions,
)


# --- a tiny hand-made matrix -------------------------------------------------
# global_rate = 0.20 on every row (the matrix builder stores it redundantly).
GLOBAL = 0.20


def tiny_matrix() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # pgroup, bgroup, n_pa, raw,  shrunk, global
            ("P_hi", "B_lo", 500, 0.40, 0.35, GLOBAL),
            ("P_hi", "B_hi", 500, 0.10, 0.15, GLOBAL),
            ("P_lo", "B_lo", 500, 0.25, 0.25, GLOBAL),
            ("P_lo", "B_hi", 500, 0.05, 0.05, GLOBAL),
        ],
        columns=[
            "pitcher_group", "batter_group", "n_pa",
            "k_rate_raw", "k_rate_shrunk", "global_rate",
        ],
    )


# --- matchup_k_rate ----------------------------------------------------------

def test_matchup_k_rate_prefers_shrunk():
    m = tiny_matrix()
    assert matchup_k_rate(m, "P_hi", "B_lo") == 0.35   # shrunk, not raw 0.40


def test_matchup_k_rate_missing_cell_falls_back_to_global():
    m = tiny_matrix()
    assert matchup_k_rate(m, "P_hi", "B_unknown") == GLOBAL
    assert matchup_k_rate(m, None, "B_lo") == GLOBAL


def test_global_rate_of():
    assert global_rate_of(tiny_matrix()) == GLOBAL
    assert math.isnan(global_rate_of(pd.DataFrame()))


# --- expected_ks_prior: hand-computed --------------------------------------

def test_prior_equals_hand_computed_sum_no_scaling():
    """scale_to_bf=False -> lambda is the plain sum of per-PA shrunk rates."""
    m = tiny_matrix()
    # Pitcher P_hi faces 3 batters: B_lo, B_hi, B_lo
    lineup = ["B_lo", "B_hi", "B_lo"]
    # shrunk rates: 0.35 + 0.15 + 0.35 = 0.85
    got = expected_ks_prior("P_hi", lineup, expected_bf=3, matrix=m, scale_to_bf=False)
    assert got == pytest.approx(0.35 + 0.15 + 0.35)


def test_prior_mean_times_bf():
    """Default scale_to_bf=True -> mean(rate) * expected_bf."""
    m = tiny_matrix()
    lineup = ["B_lo", "B_hi", "B_lo"]          # mean shrunk = 0.85/3
    bf = 27.0
    got = expected_ks_prior("P_hi", lineup, expected_bf=bf, matrix=m, scale_to_bf=True)
    assert got == pytest.approx((0.85 / 3) * bf)


def test_prior_per_batter_fallback_to_global():
    """Unknown batter groups within the lineup fall back to the global rate per cell."""
    m = tiny_matrix()
    # B_lo -> 0.35, UNKNOWN -> global 0.20  => sum 0.55
    got = expected_ks_prior("P_hi", ["B_lo", "UNKNOWN"], expected_bf=2, matrix=m,
                            scale_to_bf=False)
    assert got == pytest.approx(0.35 + GLOBAL)


def test_prior_missing_pitcher_group_global_fallback():
    """Missing pitcher group -> every cell misses -> global_rate * BF."""
    m = tiny_matrix()
    got = expected_ks_prior(None, ["B_lo", "B_hi"], expected_bf=20, matrix=m,
                            scale_to_bf=True)
    assert got == pytest.approx(GLOBAL * 20)


def test_prior_empty_lineup_global_fallback():
    m = tiny_matrix()
    got = expected_ks_prior("P_hi", [], expected_bf=25, matrix=m)
    assert got == pytest.approx(GLOBAL * 25)


# --- player_group ------------------------------------------------------------

def test_player_group_join_and_miss():
    groups = pd.DataFrame(
        {"player_id": ["alfoa001", "alfoa001", "betts001"],
         "season": [2023, 2024, 2024],
         "group": ["P_hi", "P_lo", "B_hi"]}
    )
    assert player_group(groups, "alfoa001", 2023) == "P_hi"
    assert player_group(groups, "alfoa001", 2024) == "P_lo"
    assert player_group(groups, "betts001", 2024) == "B_hi"
    assert player_group(groups, "ghost999", 2024) is None      # unknown player
    assert player_group(groups, "alfoa001", 1999) is None      # season miss


# --- MAE / improvement / gate ----------------------------------------------

def test_mae_basic():
    assert mae([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
    assert mae([1.0, 2.0], [2.0, 4.0]) == pytest.approx((1 + 2) / 2)


def test_mae_length_mismatch_raises():
    with pytest.raises(ValueError):
        mae([1.0, 2.0], [1.0])


def test_mae_empty_raises():
    with pytest.raises(ValueError):
        mae([], [])


def test_score_predictions_prior_wins():
    actual = [5.0, 6.0, 7.0]
    prior = [5.0, 6.0, 7.0]          # perfect -> MAE 0
    baseline = [4.0, 5.0, 6.0]       # off by 1 each -> MAE 1.0
    res = score_predictions(prior, baseline, actual)
    assert isinstance(res, OOSResult)
    assert res.n == 3
    assert res.prior_mae == pytest.approx(0.0)
    assert res.baseline_mae == pytest.approx(1.0)
    assert res.improvement == pytest.approx(1.0)
    assert res.beats_baseline is True


def test_score_predictions_baseline_wins_gate_fails():
    """Mirrors the disabled archetype model: prior 1.57 vs baseline 1.43 -> gate fails."""
    actual = [0.0, 0.0]
    prior = [1.57, 1.57]
    baseline = [1.43, 1.43]
    res = score_predictions(prior, baseline, actual)
    assert res.prior_mae == pytest.approx(1.57)
    assert res.baseline_mae == pytest.approx(1.43)
    assert res.improvement == pytest.approx(1.43 - 1.57)
    assert res.improvement < 0
    assert res.beats_baseline is False


def test_oosresult_as_dict_keys():
    res = score_predictions([1.0], [2.0], [1.0])
    d = res.as_dict()
    assert set(d) == {"n", "prior_mae", "baseline_mae", "improvement", "beats_baseline"}
