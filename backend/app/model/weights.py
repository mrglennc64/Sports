"""Tunable configuration for the strikeout projection engine.

Every number that drives the model lives here so it can be tuned against
backtests without touching the projection logic. The defaults encode the
"v2" framework weights.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class OpponentBlendWeights(BaseModel):
    """Sub-weights for blending the opponent's K% from its several views.

    The framework's insight: tonight's *starting lineup* K% and the
    *recent* (14/30 day) windows are more predictive than the raw
    season-vs-handedness number, so they carry more weight.
    """

    vs_handedness: float = Field(0.25, ge=0)
    last_14: float = Field(0.25, ge=0)
    last_30: float = Field(0.20, ge=0)
    starting_lineup: float = Field(0.30, ge=0)

    @model_validator(mode="after")
    def _normalize_check(self) -> "OpponentBlendWeights":
        total = self.vs_handedness + self.last_14 + self.last_30 + self.starting_lineup
        if total <= 0:
            raise ValueError("opponent blend weights must sum to a positive number")
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "vs_handedness": self.vs_handedness,
            "last_14": self.last_14,
            "last_30": self.last_30,
            "starting_lineup": self.starting_lineup,
        }


class ComponentWeights(BaseModel):
    """Top-level ensemble weights (the v2 formula). Should sum to ~1.0."""

    opponent_k_profile: float = Field(0.26, ge=0)
    pitcher_recent_form: float = Field(0.22, ge=0)
    expected_innings: float = Field(0.18, ge=0)
    lineup_strength: float = Field(0.09, ge=0)
    umpire: float = Field(0.05, ge=0)
    pitch_count: float = Field(0.04, ge=0)
    pitch_mix: float = Field(0.04, ge=0)
    # New edge-hunting factors (2026-06-13): late-breaking inputs the book is
    # slow to price. All neutral (factor 1.0) when their data is absent, so the
    # projection degrades gracefully to the prior 7-factor behaviour.
    bullpen_leash: float = Field(0.04, ge=0)
    weather: float = Field(0.04, ge=0)
    catcher_framing: float = Field(0.04, ge=0)

    @model_validator(mode="after")
    def _sums_to_one(self) -> "ComponentWeights":
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"component weights must sum to 1.0 (got {total:.4f})")
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "opponent_k_profile": self.opponent_k_profile,
            "pitcher_recent_form": self.pitcher_recent_form,
            "expected_innings": self.expected_innings,
            "lineup_strength": self.lineup_strength,
            "umpire": self.umpire,
            "pitch_count": self.pitch_count,
            "pitch_mix": self.pitch_mix,
            "bullpen_leash": self.bullpen_leash,
            "weather": self.weather,
            "catcher_framing": self.catcher_framing,
        }


class ModelConfig(BaseModel):
    """Physical constants and league baselines used to convert inputs to Ks."""

    weights: ComponentWeights = Field(default_factory=ComponentWeights)
    opponent_blend: OpponentBlendWeights = Field(default_factory=OpponentBlendWeights)

    # Conversion constants.
    batters_per_inning: float = Field(4.3, gt=0)
    pitches_per_inning: float = Field(16.0, gt=0)

    # League baselines (used as references / fallbacks).
    league_avg_k_rate: float = Field(0.22, gt=0, lt=1)
    reference_whiff_rate: float = Field(0.25, gt=0, lt=1)

    # Type-matchup synthesis blend (analytics archetype model). 0.0 = OFF (the
    # 7-factor ensemble is unchanged). >0 blends the final lambda toward the
    # archetype-regressed matchup: lambda = (1-w)*ensemble + w*type_matchup.
    # Separate from the sum-to-1 component weights on purpose. Needs pitcher_id
    # on the inputs + the exported priors file, else it's a no-op.
    type_matchup_weight: float = Field(0.0, ge=0, le=1)
    type_matchup_shrink_pa: float = Field(
        1600.0, gt=0,
        description="EB strength (in PAs) regressing a pitcher toward his archetype; "
        "the synthesis backtest's out-of-sample optimum.",
    )

    # Archetype interaction model (pitcher archetype × batter archetype). 0.0 = OFF.
    # Blends final lambda toward archetype-based K rate predictions. Requires
    # pitcher_id on inputs + archetype data files in data/exports/, else no-op.
    # When lineup includes batter_ids (future), computes per-batter interactions.
    # Enabled 2026-06-26: A/B test showed 0.5% MAE improvement, better calibration.
    archetype_weight: float = Field(0.15, ge=0, le=1)

    # Betting evaluation.
    edge_threshold_ks: float = Field(
        0.5,
        ge=0,
        description="Minimum |projection - line| (in Ks) to call a lean instead of a pass.",
    )
