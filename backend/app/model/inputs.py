"""Typed inputs for the strikeout projection engine.

These models are the contract between the (future) data layer and the model.
Today they are populated by hand or with placeholders; once the MLB Stats API
fetchers land in ``app.data`` they will return these same shapes, so the model
needs no changes to go live.

Rate fields are expressed as fractions in [0, 1] (e.g. 0.27 for a 27% K%).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Handedness(str, Enum):
    R = "R"
    L = "L"


class OpponentKProfile(BaseModel):
    """How the opposing lineup strikes out — the highest-value signal.

    Ask "how many Ks does THIS lineup allow?", not "how many does this
    pitcher get?". ``k_pct_starting_lineup`` should reflect *tonight's*
    actual nine, which is often the most predictive single number.
    """

    k_pct_vs_rhp: float = Field(..., ge=0, le=1)
    k_pct_vs_lhp: float = Field(..., ge=0, le=1)
    k_pct_last_14: float = Field(..., ge=0, le=1)
    k_pct_last_30: float = Field(..., ge=0, le=1)
    k_pct_starting_lineup: float = Field(..., ge=0, le=1)

    def k_pct_vs(self, hand: Handedness) -> float:
        return self.k_pct_vs_rhp if hand is Handedness.R else self.k_pct_vs_lhp


class PitcherRecentForm(BaseModel):
    """Recent pitcher form — last 3/5 starts beat season-long averages.

    ``recent_start_ks`` is most-recent-first (e.g. [8, 6, 9, 8, 7]).
    """

    throws: Handedness
    recent_start_ks: list[int] = Field(default_factory=list)
    k_per_9_last_30: float = Field(..., ge=0)
    swinging_strike_pct: float | None = Field(None, ge=0, le=1)
    csw_pct: float | None = Field(None, ge=0, le=1, description="Called Strikes + Whiffs %")


class ExpectedWorkload(BaseModel):
    """Volume: how many batters the pitcher is expected to face tonight.

    The most-overlooked edge — elite stuff capped at 4.2 IP misses the line.
    ``manager_hook_pitch_count`` is where this manager tends to pull the
    starter; if it bites before ``expected_innings``, volume is trimmed.
    """

    expected_innings: float = Field(..., gt=0)
    expected_pitch_count: float = Field(..., gt=0)
    manager_hook_pitch_count: float = Field(..., gt=0)


class LineupStrength(BaseModel):
    """Tonight's projected lineup K% — model the actual hitters, not the average.

    If high-K bats are resting, ``projected_lineup_k_pct`` should already
    reflect the weaker (lower-K) card that is actually playing.
    """

    projected_lineup_k_pct: float = Field(..., ge=0, le=1)
    high_k_hitters_resting: int = Field(0, ge=0)


class UmpireProfile(BaseModel):
    """Home-plate umpire's strike-zone tendency. A small but real edge."""

    historical_k_rate: float = Field(..., ge=0, le=1)
    called_strike_rate: float | None = Field(None, ge=0, le=1)


class PitchUsage(BaseModel):
    """One pitch type: how often it's thrown and how often the opponent whiffs."""

    pitch_type: str
    usage_pct: float = Field(..., ge=0, le=1)
    opponent_whiff_pct: float = Field(..., ge=0, le=1)


class PitchMixMatchup(BaseModel):
    """Pitch-type vs opponent whiff matchup (e.g. 40% sliders vs 32% whiff)."""

    pitches: list[PitchUsage] = Field(default_factory=list)


class ProjectionInputs(BaseModel):
    """The full bundle of inputs for one pitcher in one game."""

    pitcher_name: str
    opponent: OpponentKProfile
    pitcher_form: PitcherRecentForm
    workload: ExpectedWorkload
    lineup: LineupStrength
    umpire: UmpireProfile | None = None
    pitch_mix: PitchMixMatchup | None = None
