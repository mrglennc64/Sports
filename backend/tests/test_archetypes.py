from app.model.archetypes import PitcherArchetype, classify_pitcher


def test_power_pitcher():
    # 60% four-seam at 97 mph
    mix = {"FF": 60.0, "SL": 25.0, "CH": 15.0}
    assert classify_pitcher(mix, avg_fastball_velo=97.0) is PitcherArchetype.POWER


def test_breaking_heavy_outranks_power():
    # Slider+sweeper 45% -> breaking-heavy even with elite velo
    mix = {"FF": 40.0, "SL": 30.0, "ST": 15.0, "CH": 15.0}
    assert classify_pitcher(mix, avg_fastball_velo=97.0) is PitcherArchetype.BREAKING_HEAVY


def test_sinker_contact():
    mix = {"SI": 45.0, "SL": 30.0, "CH": 25.0}
    assert classify_pitcher(mix, avg_fastball_velo=93.0) is PitcherArchetype.SINKER_CONTACT


def test_finesse_offspeed():
    mix = {"FF": 45.0, "CH": 30.0, "CU": 25.0}
    assert classify_pitcher(mix, avg_fastball_velo=90.0) is PitcherArchetype.FINESSE_OFFSPEED


def test_balanced_fallback():
    mix = {"FF": 45.0, "SL": 25.0, "SI": 15.0, "CH": 15.0}
    assert classify_pitcher(mix, avg_fastball_velo=93.0) is PitcherArchetype.BALANCED


def test_unknown_pitch_codes_ignored():
    mix = {"FF": 60.0, "XX": 40.0}
    assert classify_pitcher(mix, avg_fastball_velo=96.0) is PitcherArchetype.POWER


def test_missing_velo_never_power():
    mix = {"FF": 60.0, "SL": 40.0}
    assert classify_pitcher(mix, avg_fastball_velo=None) is PitcherArchetype.BALANCED
