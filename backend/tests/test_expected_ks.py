import pytest

from app.model.expected_ks import (
    LEAGUE_AVG_K_RATE,
    PitcherInputs,
    expected_strikeouts,
    opponent_factor,
)


def test_opponent_factor_neutral_at_league_average():
    assert opponent_factor(LEAGUE_AVG_K_RATE) == pytest.approx(1.0)


def test_opponent_factor_scales_with_rate():
    assert opponent_factor(0.27) > 1.0   # high-K lineup
    assert opponent_factor(0.18) < 1.0   # contact lineup


def test_expected_strikeouts_baseline():
    # K/9 = 9, 6 IP, average opponent, neutral park/form -> exactly 6.0 Ks.
    p = PitcherInputs(
        name="Test",
        k_per_9=9.0,
        innings_per_start=6.0,
        opp_k_rate=LEAGUE_AVG_K_RATE,
    )
    assert expected_strikeouts(p) == pytest.approx(6.0)


def test_multipliers_compound():
    p = PitcherInputs(
        name="Test",
        k_per_9=9.0,
        innings_per_start=6.0,
        opp_k_rate=LEAGUE_AVG_K_RATE,
        park_factor=1.05,
        form_factor=1.10,
    )
    assert expected_strikeouts(p) == pytest.approx(6.0 * 1.05 * 1.10)
