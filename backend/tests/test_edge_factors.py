"""The 2026-06-13 edge-hunting factors: bullpen leash, weather, catcher framing.

Each is a late-breaking input the book is slow to price. The contract:
neutral (no change vs no-data) when absent, and directionally correct when
present.
"""
import pytest

from app.model.inputs import (
    BullpenContext,
    CatcherFraming,
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
    WeatherContext,
)
from app.model.projection import project


def make_inputs(**overrides) -> ProjectionInputs:
    base = dict(
        pitcher_name="Test Pitcher",
        opponent=OpponentKProfile(
            k_pct_vs_rhp=0.27, k_pct_vs_lhp=0.24, k_pct_last_14=0.295,
            k_pct_last_30=0.268, k_pct_starting_lineup=0.312,
        ),
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R, recent_start_ks=[8, 6, 9, 8, 7],
            k_per_9_last_30=9.5,
        ),
        workload=ExpectedWorkload(
            expected_innings=5.8, expected_pitch_count=95,
            manager_hook_pitch_count=100,
        ),
        lineup=LineupStrength(projected_lineup_k_pct=0.30),
    )
    base.update(overrides)
    return ProjectionInputs(**base)


def _proj(**overrides) -> float:
    return project(make_inputs(**overrides)).projected_ks


# --- neutral when absent -----------------------------------------------------

def test_no_new_data_matches_neutral_factors():
    baseline = _proj()
    neutral = _proj(
        bullpen=BullpenContext(leash_factor=1.0),
        weather=WeatherContext(k_factor=1.0),
        catcher=CatcherFraming(k_factor=1.0),
    )
    assert neutral == pytest.approx(baseline)


# --- bullpen / opener (volume) ----------------------------------------------

def test_opener_lowers_projection():
    full = _proj(bullpen=BullpenContext(is_opener=False, leash_factor=1.0))
    opener = _proj(bullpen=BullpenContext(is_opener=True, leash_factor=0.35))
    assert opener < full


def test_short_leash_lowers_projection():
    assert _proj(bullpen=BullpenContext(leash_factor=0.8)) < _proj()


def test_bullpen_component_detail_flags_opener():
    comps = {c.name: c for c in project(
        make_inputs(bullpen=BullpenContext(is_opener=True, leash_factor=0.35))
    ).components}
    assert "OPENER" in comps["bullpen_leash"].detail


# --- weather -----------------------------------------------------------------

def test_cold_weather_factor_below_one_lowers_projection():
    assert _proj(weather=WeatherContext(temperature_f=45, k_factor=0.97)) < _proj()


def test_dome_is_neutral_regardless_of_factor():
    # A dome must ignore any k_factor and stay neutral.
    domed = _proj(weather=WeatherContext(is_dome=True, k_factor=0.90))
    assert domed == pytest.approx(_proj())


# --- catcher framing ---------------------------------------------------------

def test_plus_framer_raises_projection():
    assert _proj(catcher=CatcherFraming(framing_runs=10, k_factor=1.03)) > _proj()


def test_poor_framer_lowers_projection():
    assert _proj(catcher=CatcherFraming(framing_runs=-8, k_factor=0.97)) < _proj()


# --- combined ----------------------------------------------------------------

def test_factors_stack():
    stacked = _proj(
        bullpen=BullpenContext(is_opener=True, leash_factor=0.35),
        weather=WeatherContext(temperature_f=45, k_factor=0.97),
        catcher=CatcherFraming(k_factor=0.97),
    )
    # Opener volume cut dominates; net projection well below neutral.
    assert stacked < _proj()
