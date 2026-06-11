"""Rule-based pitcher archetypes from pitch mix + fastball velocity.

Five buckets (the classic scouting taxonomy, made deterministic). Order of
checks matters: a 45%-breaking-ball pitcher is BREAKING_HEAVY regardless of
velocity. Thresholds are conventions, not fitted values — revisit only with
backtest evidence.
"""
from enum import Enum

FOUR_SEAM = {"FF", "FA"}
SINKERS = {"SI", "FT"}
BREAKING = {"SL", "ST", "SV", "CU", "KC"}
OFFSPEED = {"CH", "FS", "FO", "SC"}


class PitcherArchetype(str, Enum):
    POWER = "power"                      # four-seam dominant, 95+
    SINKER_CONTACT = "sinker_contact"    # sinker-first, pitches to contact
    BREAKING_HEAVY = "breaking_heavy"    # lives on sliders/curves (edge calls!)
    FINESSE_OFFSPEED = "finesse_offspeed"  # changeup/splitter, sub-94
    BALANCED = "balanced"                # everything else


def _share(pitch_mix: dict[str, float], codes: set[str]) -> float:
    return sum(v for k, v in pitch_mix.items() if k in codes)


def classify_pitcher(
    pitch_mix: dict[str, float], avg_fastball_velo: float | None
) -> PitcherArchetype:
    # Strictly greater than 40: an exactly-40% breaking share is not yet
    # "lives on breaking balls" (and keeps a 60/40 FF/SL pitcher out of the
    # bucket per tests/test_archetypes.py::test_missing_velo_never_power).
    if _share(pitch_mix, BREAKING) > 40:
        return PitcherArchetype.BREAKING_HEAVY
    if _share(pitch_mix, SINKERS) >= 35:
        return PitcherArchetype.SINKER_CONTACT
    if (
        _share(pitch_mix, FOUR_SEAM) >= 50
        and avg_fastball_velo is not None
        and avg_fastball_velo >= 95
    ):
        return PitcherArchetype.POWER
    if (
        _share(pitch_mix, OFFSPEED) >= 25
        and avg_fastball_velo is not None
        and avg_fastball_velo < 94
    ):
        return PitcherArchetype.FINESSE_OFFSPEED
    return PitcherArchetype.BALANCED
