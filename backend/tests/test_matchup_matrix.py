"""Synthetic tests for the group-vs-group strikeout matrix.

No real files: we hand-build a tiny groups mapping + a tiny plays DataFrame with
known K outcomes and assert the math (raw rate, shrinkage direction, coverage,
and lookup fallback).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.grouping.matchup_matrix import (
    aggregate_matchups,
    matchup_k_rate,
    to_pivot,
)


# --------------------------------------------------------------------------- #
# Synthetic fixtures
# --------------------------------------------------------------------------- #
def _groups():
    """Two pitchers (groups 0,1) and two batters (groups 0,1) in season 2020."""
    pitcher_groups = pd.DataFrame(
        {
            "player_id": ["pitchA", "pitchB"],
            "season": [2020, 2020],
            "group": [0, 1],
        }
    )
    batter_groups = pd.DataFrame(
        {
            "player_id": ["batX", "batY"],
            "season": [2020, 2020],
            "group": [0, 1],
        }
    )
    return pitcher_groups, batter_groups


def _plays():
    """Hand-built PAs with known K counts.

    Cell (pg=0, bg=0): pitchA vs batX -> LARGE cell, 1000 PAs, 400 K (raw 0.40).
    Cell (pg=1, bg=1): pitchB vs batY -> THIN cell, 4 PAs, 0 K (raw 0.00).
    A few pa==0 non-PA rows are mixed in and must be ignored.
    """
    rows = []
    # Large cell: 1000 PAs, 400 strikeouts.
    for i in range(1000):
        rows.append(
            {"pitcher": "pitchA", "batter": "batX", "pa": 1, "k": 1 if i < 400 else 0,
             "season": 2020}
        )
    # Thin cell: 4 PAs, 0 strikeouts.
    for _ in range(4):
        rows.append({"pitcher": "pitchB", "batter": "batY", "pa": 1, "k": 0, "season": 2020})
    # Non-PA noise rows (pa==0) that must be excluded.
    for _ in range(50):
        rows.append({"pitcher": "pitchA", "batter": "batX", "pa": 0, "k": 0, "season": 2020})
    return pd.DataFrame(rows)


@pytest.fixture
def matrix():
    pitcher_groups, batter_groups = _groups()
    return aggregate_matchups(_plays(), pitcher_groups, batter_groups, m=200.0)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_raw_rate_exact(matrix):
    """k_rate_raw for the large cell is exactly the hand-computed 400/1000."""
    cell = matrix[(matrix["pitcher_group"] == 0) & (matrix["batter_group"] == 0)]
    assert len(cell) == 1
    assert int(cell["n_pa"].iloc[0]) == 1000  # pa==0 rows excluded
    assert int(cell["k_sum"].iloc[0]) == 400
    assert cell["k_rate_raw"].iloc[0] == pytest.approx(0.40)


def test_global_rate(matrix):
    """Global rate = total K / total PA = 400 / 1004."""
    expected = 400 / 1004
    assert matrix["global_rate"].iloc[0] == pytest.approx(expected)


def test_thin_cell_pulled_toward_global(matrix):
    """Thin cell (raw 0.0) is shrunk UP toward the global mean."""
    global_rate = matrix["global_rate"].iloc[0]
    thin = matrix[(matrix["pitcher_group"] == 1) & (matrix["batter_group"] == 1)].iloc[0]
    assert thin["k_rate_raw"] == pytest.approx(0.0)
    # Shrunk value sits strictly between raw (0) and the global mean.
    assert thin["k_rate_raw"] < thin["k_rate_shrunk"] <= global_rate
    # With m=200 and only 4 PAs, it must be very close to the global mean.
    expected = (0 + 200 * global_rate) / (4 + 200)
    assert thin["k_rate_shrunk"] == pytest.approx(expected)
    assert abs(thin["k_rate_shrunk"] - global_rate) < 0.01


def test_large_cell_close_to_raw(matrix):
    """Large cell (1000 PAs) shrunk value stays near its raw rate."""
    large = matrix[(matrix["pitcher_group"] == 0) & (matrix["batter_group"] == 0)].iloc[0]
    assert large["k_rate_shrunk"] == pytest.approx(large["k_rate_raw"], abs=0.03)
    # And it is closer to raw than the thin cell is to its raw.
    assert abs(large["k_rate_shrunk"] - large["k_rate_raw"]) < 0.05


def test_all_present_cells_appear(matrix):
    """Every (pgroup, bgroup) actually present in the data appears in the matrix."""
    present = set(zip(matrix["pitcher_group"], matrix["batter_group"]))
    assert (0, 0) in present
    assert (1, 1) in present
    # The cross cells (0,1) and (1,0) never occurred in the synthetic data.
    assert (0, 1) not in present
    assert (1, 0) not in present


def test_lookup_hit(matrix):
    """matchup_k_rate returns the cell's shrunk rate when present."""
    cell = matrix[(matrix["pitcher_group"] == 0) & (matrix["batter_group"] == 0)].iloc[0]
    assert matchup_k_rate(matrix, 0, 0) == pytest.approx(cell["k_rate_shrunk"])


def test_lookup_fallback_to_global(matrix):
    """Unseen cell falls back to the global rate."""
    global_rate = matrix["global_rate"].iloc[0]
    assert matchup_k_rate(matrix, 0, 1) == pytest.approx(global_rate)
    assert matchup_k_rate(matrix, 99, 99) == pytest.approx(global_rate)


def test_to_pivot_shape_and_values(matrix):
    """Pivot is pitcher_group x batter_group of k_rate_shrunk."""
    pivot = to_pivot(matrix)
    assert pivot.index.name == "pitcher_group"
    assert pivot.columns.name == "batter_group"
    large = matrix[(matrix["pitcher_group"] == 0) & (matrix["batter_group"] == 0)].iloc[0]
    assert pivot.loc[0, 0] == pytest.approx(large["k_rate_shrunk"])


def test_season_specific_join():
    """Group join is per-season: a player's wrong-season group must not match."""
    pitcher_groups = pd.DataFrame(
        {"player_id": ["pitchA"], "season": [2019], "group": [0]}  # only 2019
    )
    batter_groups = pd.DataFrame(
        {"player_id": ["batX"], "season": [2020], "group": [0]}
    )
    plays = pd.DataFrame(
        {"pitcher": ["pitchA"], "batter": ["batX"], "pa": [1], "k": [1], "season": [2020]}
    )
    # pitchA has no 2020 group -> inner join drops the row -> empty matrix.
    result = aggregate_matchups(plays, pitcher_groups, batter_groups, m=200.0)
    assert result.empty
