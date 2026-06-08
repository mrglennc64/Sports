"""Strikeout projection model (v2 framework)."""

from .inputs import (
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    OpponentKProfile,
    PitchMixMatchup,
    PitchUsage,
    PitcherRecentForm,
    ProjectionInputs,
    UmpireProfile,
)
from .backtest import (
    AccuracyMetrics,
    BacktestResult,
    BettingMetrics,
    GameOutcome,
    accuracy_metrics,
    betting_metrics,
    make_synthetic_dataset,
    run_backtest,
    tune_weights,
)
from .bridge import evaluate_projection, predict_with_ensemble
from .projection import evaluate_bet, project
from .result import BetEvaluation, ComponentEstimate, Lean, ProjectionResult
from .weights import ComponentWeights, ModelConfig, OpponentBlendWeights

__all__ = [
    "AccuracyMetrics",
    "BacktestResult",
    "BetEvaluation",
    "BettingMetrics",
    "ComponentEstimate",
    "ComponentWeights",
    "GameOutcome",
    "ExpectedWorkload",
    "Handedness",
    "Lean",
    "LineupStrength",
    "ModelConfig",
    "OpponentBlendWeights",
    "OpponentKProfile",
    "PitchMixMatchup",
    "PitchUsage",
    "PitcherRecentForm",
    "ProjectionInputs",
    "ProjectionResult",
    "UmpireProfile",
    "accuracy_metrics",
    "betting_metrics",
    "evaluate_bet",
    "evaluate_projection",
    "predict_with_ensemble",
    "make_synthetic_dataset",
    "project",
    "run_backtest",
    "tune_weights",
]
