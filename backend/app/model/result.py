"""Output models for the projection engine."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ComponentEstimate(BaseModel):
    """One lens's independent strikeout estimate and how it was derived."""

    name: str
    weight: float
    estimate_ks: float
    detail: str = ""


class ProjectionResult(BaseModel):
    """The blended projection plus a full, inspectable breakdown."""

    pitcher_name: str
    projected_ks: float
    expected_batters_faced: float
    components: list[ComponentEstimate]

    def component(self, name: str) -> ComponentEstimate:
        for c in self.components:
            if c.name == name:
                return c
        raise KeyError(name)


class Lean(str, Enum):
    OVER = "OVER"
    UNDER = "UNDER"
    PASS = "PASS"


class BetEvaluation(BaseModel):
    """Projection compared against a sportsbook strikeout line."""

    pitcher_name: str
    line: float
    projected_ks: float
    edge_ks: float = Field(..., description="projection - line; positive favors the over")
    lean: Lean
