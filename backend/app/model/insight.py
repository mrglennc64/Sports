"""Decision/insight layer: translate raw model numbers into human decisions.

The model produces an edge, a Kelly stake and some context. Consumer users want a
verdict, not a probability. This layer maps the numbers to a recommendation
("Strong Play" / "Lean" / "No Bet" / "Pass"), a confidence level, a plain-English
stake size, and a list of reasons. Pure function, easily tested, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.model.expected_ks import LEAGUE_AVG_K_RATE


@dataclass
class Insight:
    recommendation: str          # "Strong Play" | "Lean" | "No Bet" | "Pass"
    confidence: str              # "High" | "Medium" | "Low"
    stake_label: str             # "—" | "Small" | "Medium" | "Large"
    signal: str                  # "strong" | "lean" | "avoid" (for color)
    reasons: list[str] = field(default_factory=list)


def _stake_label(kelly: float) -> str:
    if kelly <= 0:
        return "—"
    if kelly < 0.02:
        return "Small"
    if kelly < 0.04:
        return "Medium"
    return "Large"


def build_insight(
    *,
    side: str,
    edge: float,
    kelly: float,
    low_confidence: bool,
    opp_k_rate: float,
    park: float,
    expected_ks: float,
    line: float,
    min_edge: float,
    strong_edge: float = 0.05,
    league_avg: float = LEAGUE_AVG_K_RATE,
) -> Insight:
    reasons: list[str] = []

    # --- context reasons (the "research" feel) ---
    if opp_k_rate >= league_avg * 1.07:
        reasons.append("Opponent strikes out at a high rate")
    elif opp_k_rate <= league_avg * 0.93:
        reasons.append("Contact-heavy opponent (low strikeout rate)")
    if park >= 1.03:
        reasons.append("Ballpark tends to boost strikeouts")
    elif park <= 0.97:
        reasons.append("Ballpark tends to suppress strikeouts")

    gap = expected_ks - line
    if gap >= 0.75:
        reasons.append(f"Model projects {expected_ks:.1f} Ks, above the {line} line")
    elif gap <= -0.75:
        reasons.append(f"Model projects {expected_ks:.1f} Ks, below the {line} line")

    # --- verdict ---
    if low_confidence:
        reasons.insert(0, "Not enough starts this season to trust the projection")
        return Insight("Pass", "Low", "—", "avoid", reasons)

    if edge >= strong_edge and kelly > 0:
        rec, conf, signal = "Strong Play", "High", "strong"
    elif edge >= min_edge and kelly > 0:
        rec, conf, signal = "Lean", "Medium", "lean"
    else:
        rec, conf, signal = "No Bet", "Low", "avoid"
        reasons.append("Model and market roughly agree — no value")

    direction = "Over" if side == "over" else "Under"
    reasons.insert(0, f"{direction} {line} carries +{edge * 100:.1f}% model edge")
    return Insight(rec, conf, _stake_label(kelly), signal, reasons)
