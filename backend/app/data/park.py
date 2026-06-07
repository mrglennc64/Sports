"""Static park-factor table for strikeouts.

Values are multipliers (1.0 = neutral). >1 means the park tends to inflate
strikeouts (e.g. pitcher-friendly, poor hitting backdrop), <1 means it suppresses
them. These are coarse, hand-set approximations keyed by MLB venue name; refine
later with real park-factor data (e.g. from Statcast / FanGraphs) keyed by venue id.

Unknown venues fall back to neutral (1.0) rather than failing.
"""
from __future__ import annotations

# Keyed by the venue name string returned by the MLB Stats API schedule feed.
PARK_K_FACTORS: dict[str, float] = {
    "Oracle Park": 1.04,           # spacious, marine layer
    "Petco Park": 1.04,
    "T-Mobile Park": 1.05,
    "loanDepot park": 1.03,
    "Comerica Park": 1.02,
    "Citi Field": 1.02,
    "Yankee Stadium": 1.00,
    "Fenway Park": 0.98,
    "Wrigley Field": 0.99,
    "Dodger Stadium": 1.01,
    "Coors Field": 0.95,           # thin air suppresses breaking-ball whiffs
    "Great American Ball Park": 0.99,
    "Globe Life Field": 1.00,
    "Truist Park": 1.00,
    "Busch Stadium": 1.01,
    "American Family Field": 1.00,
    "Target Field": 1.00,
    "Kauffman Stadium": 0.99,
    "Angel Stadium": 1.01,
    "Chase Field": 1.00,
    "Citizens Bank Park": 1.00,
    "Nationals Park": 1.00,
    "Oriole Park at Camden Yards": 1.00,
    "Progressive Field": 1.02,
    "Guaranteed Rate Field": 1.00,
    "Rate Field": 1.00,
    "PNC Park": 1.01,
    "Minute Maid Park": 1.00,
    "Daikin Park": 1.00,
    "Tropicana Field": 1.02,
    "Rogers Centre": 1.00,
    "Sutter Health Park": 1.00,
}

NEUTRAL = 1.0


def park_factor(venue_name: str | None) -> float:
    if not venue_name:
        return NEUTRAL
    return PARK_K_FACTORS.get(venue_name, NEUTRAL)
