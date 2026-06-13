"""Backtesting and weight-tuning for the strikeout projection model.

Given a historical dataset of games (the pitcher's :class:`ProjectionInputs`,
the actual strikeouts thrown, and optionally the sportsbook line), this module
scores the model's accuracy (MAE / RMSE / bias) and its betting performance
(win rate / ROI), and searches the 7-weight ensemble simplex for the weights
that minimise error or maximise ROI.

.. note::
    :func:`make_synthetic_dataset` produces *placeholder* games so this module
    is runnable today, before the real data layer lands. Once the historical
    fetchers in ``app.data`` (built concurrently) can feed real games as
    :class:`GameOutcome` records, swap the synthetic generator for those.
"""

from __future__ import annotations

import math
import random
from typing import Literal

from pydantic import BaseModel, Field

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
from .projection import evaluate_bet, project
from .result import Lean
from .weights import ComponentWeights, ModelConfig

# -110 odds: risk 1 unit to win ~0.909 units.
WIN_UNITS = 100.0 / 110.0
LOSS_UNITS = -1.0

_WEIGHT_FIELDS = (
    "opponent_k_profile",
    "pitcher_recent_form",
    "expected_innings",
    "lineup_strength",
    "umpire",
    "pitch_count",
    "pitch_mix",
    "bullpen_leash",
    "weather",
    "catcher_framing",
)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #
class GameOutcome(BaseModel):
    """One historical game: model inputs plus the realised result."""

    inputs: ProjectionInputs
    actual_ks: int = Field(..., ge=0)
    line: float | None = None


# --------------------------------------------------------------------------- #
# Result models
# --------------------------------------------------------------------------- #
class AccuracyMetrics(BaseModel):
    """Point-projection accuracy over a dataset."""

    n: int
    mae: float = Field(..., description="Mean absolute error |projection - actual|")
    rmse: float = Field(..., description="Root mean squared error")
    bias: float = Field(..., description="Mean (projection - actual); >0 = over-projecting")


class BettingMetrics(BaseModel):
    """Betting performance over the records that carried a line."""

    n_plays: int = Field(..., description="Non-PASS leans (pushes included)")
    wins: int
    losses: int
    pushes: int
    win_rate: float = Field(..., description="wins / (wins + losses); pushes excluded")
    roi: float = Field(..., description="Units won per unit staked at -110")


class BacktestResult(BaseModel):
    """Full backtest report for one :class:`ModelConfig`."""

    accuracy: AccuracyMetrics
    betting: BettingMetrics | None = None


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _bet_won(lean: Lean, actual_ks: int, line: float) -> str | None:
    """Return ``"win"`` / ``"loss"`` / ``"push"`` for a non-PASS lean, else None."""
    if lean is Lean.PASS:
        return None
    if actual_ks == line:  # exact tie on an integer line -> push
        return "push"
    over_hit = actual_ks > line
    if lean is Lean.OVER:
        return "win" if over_hit else "loss"
    return "win" if not over_hit else "loss"


def accuracy_metrics(dataset: list[GameOutcome], cfg: ModelConfig | None = None) -> AccuracyMetrics:
    """Project each game and summarise point-projection error."""
    cfg = cfg or ModelConfig()
    if not dataset:
        return AccuracyMetrics(n=0, mae=0.0, rmse=0.0, bias=0.0)
    errs = [project(g.inputs, cfg).projected_ks - g.actual_ks for g in dataset]
    n = len(errs)
    mae = sum(abs(e) for e in errs) / n
    rmse = math.sqrt(sum(e * e for e in errs) / n)
    bias = sum(errs) / n
    return AccuracyMetrics(n=n, mae=mae, rmse=rmse, bias=bias)


def betting_metrics(dataset: list[GameOutcome], cfg: ModelConfig | None = None) -> BettingMetrics:
    """Evaluate leans against lines and tally win rate / ROI at -110."""
    cfg = cfg or ModelConfig()
    wins = losses = pushes = 0
    units = 0.0
    for g in dataset:
        if g.line is None:
            continue
        result = project(g.inputs, cfg)
        ev = evaluate_bet(result, g.line, cfg)
        outcome = _bet_won(ev.lean, g.actual_ks, g.line)
        if outcome is None:
            continue
        if outcome == "win":
            wins += 1
            units += WIN_UNITS
        elif outcome == "loss":
            losses += 1
            units += LOSS_UNITS
        else:
            pushes += 1
    n_plays = wins + losses + pushes
    decided = wins + losses
    win_rate = wins / decided if decided else 0.0
    roi = units / n_plays if n_plays else 0.0
    return BettingMetrics(
        n_plays=n_plays,
        wins=wins,
        losses=losses,
        pushes=pushes,
        win_rate=win_rate,
        roi=roi,
    )


def run_backtest(dataset: list[GameOutcome], cfg: ModelConfig | None = None) -> BacktestResult:
    """Compute accuracy metrics, plus betting metrics if any game has a line."""
    cfg = cfg or ModelConfig()
    acc = accuracy_metrics(dataset, cfg)
    has_lines = any(g.line is not None for g in dataset)
    bet = betting_metrics(dataset, cfg) if has_lines else None
    return BacktestResult(accuracy=acc, betting=bet)


# --------------------------------------------------------------------------- #
# Weight tuning
# --------------------------------------------------------------------------- #
def _normalize(vec: list[float]) -> list[float]:
    """Clamp negatives to 0 and renormalise so the vector sums to exactly 1.0."""
    clamped = [max(0.0, v) for v in vec]
    total = sum(clamped)
    if total <= 0:
        n = len(clamped)
        return [1.0 / n] * n
    return [v / total for v in clamped]


def _weights_from_vec(vec: list[float]) -> ComponentWeights:
    return ComponentWeights(**dict(zip(_WEIGHT_FIELDS, _normalize(vec))))


def _score(
    dataset: list[GameOutcome], cfg: ModelConfig, weights: ComponentWeights, objective: str
) -> float:
    cfg = cfg.model_copy(update={"weights": weights})
    if objective == "roi":
        return betting_metrics(dataset, cfg).roi
    return accuracy_metrics(dataset, cfg).mae


def _better(a: float, b: float, objective: str) -> bool:
    """Is score ``a`` better than ``b``? Lower MAE / higher ROI wins."""
    return a > b if objective == "roi" else a < b


def tune_weights(
    dataset: list[GameOutcome],
    base_cfg: ModelConfig | None = None,
    objective: Literal["mae", "roi"] = "mae",
    *,
    n_random: int = 200,
    n_refine: int = 60,
    step: float = 0.1,
    seed: int = 0,
) -> tuple[ComponentWeights, float]:
    """Search the 7-weight simplex for the best weights under ``objective``.

    Strategy: seeded random search over Dirichlet-like normalized vectors,
    followed by coordinate-descent refinement around the best candidate. Every
    candidate is renormalised to sum to 1.0 so ``ComponentWeights`` validates.
    Returns ``(best_weights, best_score)``; lower MAE / higher ROI is better.
    """
    base_cfg = base_cfg or ModelConfig()
    rng = random.Random(seed)

    # Seed the search with the current (default/base) weights.
    best_w = base_cfg.weights
    best_s = _score(dataset, base_cfg, best_w, objective)

    # 1. Random search: Dirichlet samples via -log(uniform), then normalize.
    for _ in range(n_random):
        vec = [-math.log(rng.random() + 1e-12) for _ in _WEIGHT_FIELDS]
        cand = _weights_from_vec(vec)
        s = _score(dataset, base_cfg, cand, objective)
        if _better(s, best_s, objective):
            best_w, best_s = cand, s

    # 2. Coordinate descent: nudge one weight up/down, renormalize, keep gains.
    cur = list(_weights_from_vec(list(best_w.as_dict().values())))
    cur_w = best_w.as_dict()
    cur = [cur_w[f] for f in _WEIGHT_FIELDS]
    for _ in range(n_refine):
        improved = False
        for i in range(len(_WEIGHT_FIELDS)):
            for delta in (step, -step):
                trial = list(cur)
                trial[i] += delta
                if trial[i] < 0:
                    continue
                cand = _weights_from_vec(trial)
                s = _score(dataset, base_cfg, cand, objective)
                if _better(s, best_s, objective):
                    best_w, best_s = cand, s
                    cur = [cand.as_dict()[f] for f in _WEIGHT_FIELDS]
                    improved = True
        if not improved:
            step *= 0.5
            if step < 1e-3:
                break
    return best_w, best_s


# --------------------------------------------------------------------------- #
# Synthetic dataset (placeholder until app.data feeds real games)
# --------------------------------------------------------------------------- #
def _synthetic_inputs(rng: random.Random) -> tuple[ProjectionInputs, float]:
    """Build one plausible game's inputs and a 'true' latent K rate per batter."""
    throws = rng.choice([Handedness.R, Handedness.L])

    opp_base = rng.uniform(0.18, 0.30)

    def jit(x: float, s: float = 0.02) -> float:
        return min(0.45, max(0.10, x + rng.uniform(-s, s)))

    opponent = OpponentKProfile(
        k_pct_vs_rhp=jit(opp_base),
        k_pct_vs_lhp=jit(opp_base),
        k_pct_last_14=jit(opp_base),
        k_pct_last_30=jit(opp_base),
        k_pct_starting_lineup=jit(opp_base),
    )

    k_per_9 = rng.uniform(6.5, 12.5)
    pitcher_form = PitcherRecentForm(
        throws=throws,
        recent_start_ks=[max(0, round(rng.gauss(k_per_9 * 0.65, 1.5))) for _ in range(5)],
        k_per_9_last_30=k_per_9,
        swinging_strike_pct=rng.uniform(0.08, 0.16),
        csw_pct=rng.uniform(0.26, 0.34),
    )

    expected_innings = rng.uniform(4.5, 6.8)
    workload = ExpectedWorkload(
        expected_innings=expected_innings,
        expected_pitch_count=rng.uniform(85, 105),
        manager_hook_pitch_count=rng.uniform(95, 110),
    )

    lineup = LineupStrength(
        projected_lineup_k_pct=jit(opp_base, 0.03),
        high_k_hitters_resting=rng.choice([0, 0, 0, 1, 2]),
    )
    umpire = UmpireProfile(historical_k_rate=rng.uniform(0.20, 0.25))
    pitch_mix = PitchMixMatchup(
        pitches=[
            PitchUsage(pitch_type="FF", usage_pct=0.45, opponent_whiff_pct=rng.uniform(0.15, 0.25)),
            PitchUsage(pitch_type="SL", usage_pct=0.35, opponent_whiff_pct=rng.uniform(0.25, 0.40)),
            PitchUsage(pitch_type="CH", usage_pct=0.20, opponent_whiff_pct=rng.uniform(0.20, 0.32)),
        ]
    )

    inputs = ProjectionInputs(
        pitcher_name="Synthetic Pitcher",
        opponent=opponent,
        pitcher_form=pitcher_form,
        workload=workload,
        lineup=lineup,
        umpire=umpire,
        pitch_mix=pitch_mix,
    )

    # "True" latent K rate per batter blends opponent and pitcher signals.
    batters_per_9 = 4.3 * 9.0
    pitcher_k = k_per_9 / batters_per_9
    true_k_pct = 0.55 * opp_base + 0.45 * pitcher_k
    return inputs, true_k_pct


def make_synthetic_dataset(n: int = 200, seed: int = 0) -> list[GameOutcome]:
    """Generate ``n`` plausible :class:`GameOutcome` records with real signal.

    Placeholder data for development/testing only -- replace with historical
    games from ``app.data`` once that layer exists. ``actual_ks`` is drawn as a
    noisy function of the inputs so weight tuning has something real to learn.
    """
    rng = random.Random(seed)
    dataset: list[GameOutcome] = []
    for _ in range(n):
        inputs, true_k_pct = _synthetic_inputs(rng)
        bf = inputs.workload.expected_innings * 4.3
        mean_ks = bf * true_k_pct
        actual = max(0, round(rng.gauss(mean_ks, 1.4)))
        # Line set near the truth with a little market noise; half-point lines
        # are common, so nudge toward a .5 to exercise both win and push paths.
        line = round(mean_ks + rng.uniform(-0.8, 0.8)) + rng.choice([0.0, 0.5])
        dataset.append(GameOutcome(inputs=inputs, actual_ks=actual, line=line))
    return dataset
