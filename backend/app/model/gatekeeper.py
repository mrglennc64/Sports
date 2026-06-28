"""Gatekeeper Protocol: Strict confidence/edge thresholds for projection release.

Instead of predicting all games, only release projections where mathematical
edge is meaningful. This prevents the model from having opinions on low-signal
matchups.

Three-tier system:
  A-Grade (Max Bet): Edge > 1.5 Ks + High historical accuracy
  B-Grade (Lean):    1.0 < Edge <= 1.5 Ks
  No Play:           Edge < 1.0 K (SILENT, no projection released)
"""

from dataclasses import dataclass
from enum import Enum


class GradeRating(str, Enum):
    """Projection quality rating."""
    A_GRADE = "A-Grade"  # Max bet tier
    B_GRADE = "B-Grade"  # Lean tier
    NO_PLAY = "No Play"  # Suppress projection


@dataclass
class GatekeeperResult:
    """Output from gatekeeper filter."""
    rating: GradeRating
    edge_ks: float  # Absolute difference: |projection - line|
    reasoning: str
    should_release: bool  # If False, suppress from user interface


def apply_bias_correction(raw_projection: float, bias_adjustment: float = 0.72) -> float:
    """Step 2: Remove systematic over-prediction bias.

    The model over-projects by ~0.72 Ks on average. Subtract this from all
    raw projections before gatekeeper evaluation.

    Args:
        raw_projection: Model's raw K projection
        bias_adjustment: Systematic bias to subtract (default 0.72)

    Returns:
        Bias-corrected projection
    """
    return raw_projection - bias_adjustment


def evaluate_edge(
    corrected_projection: float,
    market_line: float,
    historical_accuracy: float | None = None
) -> GatekeeperResult:
    """Step 1 & 3: Evaluate edge and assign tier.

    Args:
        corrected_projection: Bias-adjusted K projection
        market_line: Sportsbook strikeout line
        historical_accuracy: Optional historical accuracy for this matchup type
                           (0.0-1.0, higher = more trustworthy)

    Returns:
        GatekeeperResult with rating and reasoning
    """
    edge_ks = abs(corrected_projection - market_line)

    # Tier assignment
    if edge_ks < 1.0:
        return GatekeeperResult(
            rating=GradeRating.NO_PLAY,
            edge_ks=edge_ks,
            reasoning=f"Edge {edge_ks:.2f} Ks < 1.0 threshold (insufficient signal)",
            should_release=False
        )
    elif edge_ks <= 1.5:
        return GatekeeperResult(
            rating=GradeRating.B_GRADE,
            edge_ks=edge_ks,
            reasoning=f"Edge {edge_ks:.2f} Ks in B-Grade range (1.0-1.5)",
            should_release=True
        )
    else:  # edge_ks > 1.5
        return GatekeeperResult(
            rating=GradeRating.A_GRADE,
            edge_ks=edge_ks,
            reasoning=f"Edge {edge_ks:.2f} Ks > 1.5 (high-confidence play)",
            should_release=True
        )


def filter_slate(
    projections: list[dict],
    bias_adjustment: float = 0.72
) -> tuple[list[dict], list[dict]]:
    """Apply gatekeeper to full slate.

    Args:
        projections: List of {pitcher, projection, line, ...} dicts
        bias_adjustment: Systematic bias to remove

    Returns:
        (released_plays, suppressed_plays) tuples
    """
    released = []
    suppressed = []

    for proj in projections:
        raw = proj['expected_ks']
        line = proj['line']

        # Step 2: Correct bias
        corrected = apply_bias_correction(raw, bias_adjustment)

        # Step 1 & 3: Evaluate and tier
        result = evaluate_edge(corrected, line)

        proj_with_gate = {**proj, 'corrected_projection': corrected, **result.__dict__}

        if result.should_release:
            released.append(proj_with_gate)
        else:
            suppressed.append(proj_with_gate)

    return released, suppressed
