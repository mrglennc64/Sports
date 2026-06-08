"""The strikeout projection engine (v2 framework, ensemble form).

Each of the seven framework factors produces its *own* independent estimate
of the pitcher's total strikeouts. The final projection is the weighted blend
of those estimates using the configurable v2 weights. Every component is
returned in the breakdown so a bettor can see what each lens says.

Mapping of the framework to this engine:

  1. Opponent K profile   30%   bf x blended opponent K%
  2. Pitcher recent form  25%   recent per-start Ks (falls back to K/9)
  3. Expected innings     20%   bf x neutral K% (the volume anchor)
  4. Lineup strength      10%   bf x tonight's projected lineup K%
  5. Umpire                5%   neutral estimate x umpire K factor
  6. Pitch count           5%   manager-hook-trimmed bf x neutral K%
  7. Pitch mix             5%   neutral estimate x weighted-whiff factor

where ``bf`` = expected batters faced and the "neutral K%" is the average of
the pitcher's recent K% and the opponent's blended K%.
"""

from __future__ import annotations

from statistics import mean

from .inputs import ProjectionInputs
from .result import BetEvaluation, ComponentEstimate, Lean, ProjectionResult
from .weights import ModelConfig


def _blended_opponent_k_pct(inputs: ProjectionInputs, cfg: ModelConfig) -> float:
    opp = inputs.opponent
    bw = cfg.opponent_blend
    parts = {
        "vs_handedness": opp.k_pct_vs(inputs.pitcher_form.throws),
        "last_14": opp.k_pct_last_14,
        "last_30": opp.k_pct_last_30,
        "starting_lineup": opp.k_pct_starting_lineup,
    }
    sub = bw.as_dict()
    total_w = sum(sub.values())
    return sum(parts[k] * sub[k] for k in parts) / total_w


def _pitcher_recent_k_pct(inputs: ProjectionInputs, cfg: ModelConfig) -> float:
    """Pitcher's recent K rate per batter, derived from K/9."""
    batters_per_9 = cfg.batters_per_inning * 9.0
    return inputs.pitcher_form.k_per_9_last_30 / batters_per_9


def _expected_batters_faced(innings: float, cfg: ModelConfig) -> float:
    return innings * cfg.batters_per_inning


def project(inputs: ProjectionInputs, cfg: ModelConfig | None = None) -> ProjectionResult:
    """Run the full ensemble projection for one pitcher in one game."""
    cfg = cfg or ModelConfig()
    w = cfg.weights

    bf = _expected_batters_faced(inputs.workload.expected_innings, cfg)
    opp_k = _blended_opponent_k_pct(inputs, cfg)
    pitcher_k = _pitcher_recent_k_pct(inputs, cfg)
    neutral_k = (opp_k + pitcher_k) / 2.0
    neutral_estimate = bf * neutral_k

    components: list[ComponentEstimate] = []

    # 1. Opponent K profile.
    components.append(
        ComponentEstimate(
            name="opponent_k_profile",
            weight=w.opponent_k_profile,
            estimate_ks=bf * opp_k,
            detail=f"{bf:.1f} BF x {opp_k:.1%} blended opp K%",
        )
    )

    # 2. Pitcher recent form: prefer actual recent per-start Ks.
    recent = inputs.pitcher_form.recent_start_ks
    if recent:
        form_estimate = mean(recent)
        form_detail = f"mean of last {len(recent)} starts = {form_estimate:.1f} Ks"
    else:
        form_estimate = bf * pitcher_k
        form_detail = f"{bf:.1f} BF x {pitcher_k:.1%} (from K/9)"
    components.append(
        ComponentEstimate(
            name="pitcher_recent_form",
            weight=w.pitcher_recent_form,
            estimate_ks=form_estimate,
            detail=form_detail,
        )
    )

    # 3. Expected innings (volume anchor).
    components.append(
        ComponentEstimate(
            name="expected_innings",
            weight=w.expected_innings,
            estimate_ks=neutral_estimate,
            detail=f"{bf:.1f} BF x {neutral_k:.1%} neutral K%",
        )
    )

    # 4. Lineup strength: tonight's actual card.
    lineup_k = inputs.lineup.projected_lineup_k_pct
    components.append(
        ComponentEstimate(
            name="lineup_strength",
            weight=w.lineup_strength,
            estimate_ks=bf * lineup_k,
            detail=f"{bf:.1f} BF x {lineup_k:.1%} projected lineup K%"
            + (
                f" ({inputs.lineup.high_k_hitters_resting} high-K bat(s) resting)"
                if inputs.lineup.high_k_hitters_resting
                else ""
            ),
        )
    )

    # 5. Umpire factor (nudge on the neutral estimate).
    if inputs.umpire is not None:
        ump_factor = inputs.umpire.historical_k_rate / cfg.league_avg_k_rate
        ump_detail = f"neutral x {ump_factor:.3f} ump K factor"
    else:
        ump_factor = 1.0
        ump_detail = "no umpire data; neutral"
    components.append(
        ComponentEstimate(
            name="umpire",
            weight=w.umpire,
            estimate_ks=neutral_estimate * ump_factor,
            detail=ump_detail,
        )
    )

    # 6. Pitch count / manager hook trims volume.
    hook_innings = inputs.workload.manager_hook_pitch_count / cfg.pitches_per_inning
    eff_innings = min(inputs.workload.expected_innings, hook_innings)
    eff_bf = _expected_batters_faced(eff_innings, cfg)
    components.append(
        ComponentEstimate(
            name="pitch_count",
            weight=w.pitch_count,
            estimate_ks=eff_bf * neutral_k,
            detail=f"{eff_innings:.1f} eff IP ({eff_bf:.1f} BF) x {neutral_k:.1%}",
        )
    )

    # 7. Pitch mix matchup factor.
    if inputs.pitch_mix is not None and inputs.pitch_mix.pitches:
        used = sum(p.usage_pct for p in inputs.pitch_mix.pitches)
        if used > 0:
            weighted_whiff = (
                sum(p.usage_pct * p.opponent_whiff_pct for p in inputs.pitch_mix.pitches)
                / used
            )
            mix_factor = weighted_whiff / cfg.reference_whiff_rate
            mix_detail = f"neutral x {mix_factor:.3f} (whiff {weighted_whiff:.1%})"
        else:
            mix_factor = 1.0
            mix_detail = "zero pitch usage; neutral"
    else:
        mix_factor = 1.0
        mix_detail = "no pitch-mix data; neutral"
    components.append(
        ComponentEstimate(
            name="pitch_mix",
            weight=w.pitch_mix,
            estimate_ks=neutral_estimate * mix_factor,
            detail=mix_detail,
        )
    )

    projected = sum(c.weight * c.estimate_ks for c in components)

    return ProjectionResult(
        pitcher_name=inputs.pitcher_name,
        projected_ks=projected,
        expected_batters_faced=bf,
        components=components,
    )


def evaluate_bet(
    result: ProjectionResult, line: float, cfg: ModelConfig | None = None
) -> BetEvaluation:
    """Compare a projection to a sportsbook strikeout line and lean over/under."""
    cfg = cfg or ModelConfig()
    edge = result.projected_ks - line
    if edge >= cfg.edge_threshold_ks:
        lean = Lean.OVER
    elif edge <= -cfg.edge_threshold_ks:
        lean = Lean.UNDER
    else:
        lean = Lean.PASS
    return BetEvaluation(
        pitcher_name=result.pitcher_name,
        line=line,
        projected_ks=result.projected_ks,
        edge_ks=edge,
        lean=lean,
    )
