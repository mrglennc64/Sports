"""Bridge the v2 ensemble projection into the Poisson/edge/insight betting stack.

The ensemble in :mod:`app.model.projection` produces a richer expected-Ks
(``lambda``) from recent form, tonight's actual lineup, expected innings, the
home-plate umpire, manager hook and pitch mix. This module feeds that lambda
into the *existing* probability + edge + Kelly + insight machinery
(:mod:`app.model.poisson`, :mod:`app.model.edge`, :mod:`app.model.insight`), so
we keep the predictive inputs of the framework AND the rigorous de-vigged
staking of the original pipeline — one model end to end.

This is the "bridge" that unifies the two model tracks: instead of computing
lambda from season K/9 x multipliers, the betting stack now consumes the
ensemble's lambda. Output shape matches ``pipeline.predict_pitcher`` so it is a
drop-in for the API/pipeline.
"""

from __future__ import annotations

from app.config import Settings
from app.config import settings as default_settings
from app.model import kelly, poisson
from app.model.calibration import shrink_to_even
from app.model.edge import evaluate_prop, prob_to_american
from app.model.expected_ks import LEAGUE_AVG_K_RATE
from app.model.insight import build_insight
from app.model.inputs import ProjectionInputs
from app.model.projection import project
from app.model.result import ProjectionResult
from app.model.weights import ModelConfig


def evaluate_projection(
    result: ProjectionResult,
    *,
    line: float,
    over_odds: float | None = None,
    under_odds: float | None = None,
    opp_k_rate: float = LEAGUE_AVG_K_RATE,
    park: float = 1.0,
    low_confidence: bool = False,
    settings: Settings = default_settings,
) -> dict:
    """Turn an ensemble projection into Poisson probabilities, edge and a verdict.

    ``opp_k_rate`` and ``park`` only feed the human-readable insight reasons;
    the projection itself already accounts for the opponent. If book odds are
    omitted, only the projection + fair odds are returned (no edge/Kelly).
    """
    lam = result.projected_ks
    p_over = poisson.prob_over(lam, line)
    p_under = poisson.prob_under(lam, line)
    # Pull overconfident probabilities back toward the market (1.0 = off).
    if settings.prob_shrinkage != 1.0:
        p_over = shrink_to_even(p_over, settings.prob_shrinkage)
        p_under = shrink_to_even(p_under, settings.prob_shrinkage)

    out: dict = {
        "pitcher": result.pitcher_name,
        "expected_ks": round(lam, 3),
        "expected_batters_faced": round(result.expected_batters_faced, 2),
        "line": line,
        "prob_over": round(p_over, 4),
        "prob_under": round(p_under, 4),
        "fair_over_odds": round(prob_to_american(p_over), 1) if p_over > 0 else None,
        "fair_under_odds": round(prob_to_american(p_under), 1) if p_under > 0 else None,
        "components": {c.name: round(c.estimate_ks, 3) for c in result.components},
    }

    if over_odds is None or under_odds is None:
        return out

    best = evaluate_prop(
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        model_prob_over=p_over,
        model_prob_under=p_under,
        kelly_fraction_=settings.kelly_fraction,
        kelly_cap=settings.kelly_cap,
        devig_method=settings.devig_method,
    )
    insight = build_insight(
        side=best.side,
        edge=best.edge,
        kelly=best.kelly,
        low_confidence=low_confidence,
        opp_k_rate=opp_k_rate,
        park=park,
        expected_ks=lam,
        line=line,
        min_edge=settings.min_edge,
    )

    # Calculate kelly_fraction and suggested_bet_size from the model probability
    kelly_fraction = None
    suggested_bet_size = None
    if best.side == "over":
        kelly_fraction = kelly.calculate_kelly_fraction(
            model_probability=p_over,
            market_probability=best.fair_prob,
            american_odds=over_odds,
            kelly_fraction_fraction=settings.kelly_fraction
        )
    else:  # under
        kelly_fraction = kelly.calculate_kelly_fraction(
            model_probability=p_under,
            market_probability=best.fair_prob,
            american_odds=under_odds,
            kelly_fraction_fraction=settings.kelly_fraction
        )

    if kelly_fraction and kelly_fraction > 0:
        suggested_bet_size = kelly.calculate_bet_size(kelly_fraction, 1000.0)

    out.update(
        {
            "side": best.side,
            "model_prob": round(best.model_prob, 4),
            "fair_prob": round(best.fair_prob, 4),
            "over_odds": over_odds,
            "under_odds": under_odds,
            "edge": round(best.edge, 4),
            "kelly": round(best.kelly, 4),
            "kelly_fraction": round(kelly_fraction, 4) if kelly_fraction else None,
            "suggested_bet_size": round(suggested_bet_size, 2) if suggested_bet_size else None,
            "bet": best.edge >= settings.min_edge
            and best.kelly > 0
            and not low_confidence,
            "low_confidence": low_confidence,
            "recommendation": insight.recommendation,
            "confidence": insight.confidence,
            "stake_label": insight.stake_label,
            "signal": insight.signal,
            "reasons": insight.reasons,
        }
    )
    return out


def predict_with_ensemble(
    inputs: ProjectionInputs,
    *,
    line: float,
    over_odds: float | None = None,
    under_odds: float | None = None,
    park: float = 1.0,
    low_confidence: bool | None = None,
    cfg: ModelConfig | None = None,
    settings: Settings = default_settings,
) -> dict:
    """Run the full ensemble -> Poisson -> edge path for one start.

    The headline opponent K% used for the insight reasons is tonight's
    projected-lineup K% (the framework's most predictive opponent signal).

    ``low_confidence``: None (default) derives it from the season sample —
    fewer than ``settings.min_recent_starts`` starts this season means the
    inputs are too thin for a confident verdict (the restored v1 gate).
    Pass an explicit bool to override.
    """
    if low_confidence is None:
        low_confidence = (
            len(inputs.pitcher_form.recent_start_ks) < settings.min_recent_starts
        )
    result = project(inputs, cfg)
    return evaluate_projection(
        result,
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        opp_k_rate=inputs.lineup.projected_lineup_k_pct,
        park=park,
        low_confidence=low_confidence,
        settings=settings,
    )
