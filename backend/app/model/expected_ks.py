"""Expected strikeouts (lambda) for a pitcher's start.

    lambda = (K/9 / 9) * IP_proj * M_opp * M_park * M_form

Each multiplier is normalised around 1.0 so the baseline (K/9 * innings) is only
adjusted, not distorted. This is the deterministic baseline; an ML correction can
later multiply ``lambda`` by a learned factor without changing this signature.
"""
from __future__ import annotations

from dataclasses import dataclass

# League-average team strikeout rate (K / plate appearance). Used to normalise the
# opponent factor so an average lineup yields M_opp == 1.0. ~22.5% in recent seasons.
LEAGUE_AVG_K_RATE = 0.225


@dataclass
class PitcherInputs:
    name: str
    k_per_9: float          # season strikeouts per 9 innings
    innings_per_start: float  # season IP / games started
    opp_k_rate: float       # opponent team K per plate appearance
    park_factor: float = 1.0
    form_factor: float = 1.0  # recent-form multiplier (1.0 = neutral; wired later)


def opponent_factor(opp_k_rate: float, league_avg: float = LEAGUE_AVG_K_RATE) -> float:
    """Opponent strikeout-proneness relative to league average.

    A lineup that strikes out more than average (>league_avg) pushes the factor
    above 1.0, raising expected Ks; a contact-heavy lineup pulls it below 1.0.
    """
    if league_avg <= 0:
        return 1.0
    return opp_k_rate / league_avg


def expected_strikeouts(p: PitcherInputs) -> float:
    base = (p.k_per_9 / 9.0) * p.innings_per_start
    m_opp = opponent_factor(p.opp_k_rate)
    return base * m_opp * p.park_factor * p.form_factor
