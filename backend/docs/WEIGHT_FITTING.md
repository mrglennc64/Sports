# Weight fitting — Step 1: the factor-projection dataset (and what it revealed)

The ensemble's 10 component weights (`model/weights.py`) are expert priors, not fitted.
Fitting them requires a dataset of per-factor projections over many historical starts —
which did not exist (`predictions.csv` logs only the final λ). Step 1 built it, and in
doing so answered the more important question: **is weight optimization even worth it?**

## What was built

`app/fit/factor_backfill.py` reconstructs `ProjectionInputs` for each historical start
**from Retrosheet, leak-free** (only games strictly before the start date), runs the
production `project()` ensemble, and records all 10 component estimates + actual Ks.
The dominant factors (opponent K profile, recent form, expected innings, lineup = 75%
of the weight) are reconstructed; the minor factors are neutral-defaulted. Validated on
2024: **3,926 starts, 0 failures.**

## The headline finding: the 10 factors are ~2 effective dimensions

On the real 2024 data, each component's correlation with actual Ks:

| component | corr w/ actual | note |
|---|---|---|
| opponent_k_profile | +0.364 | ┐ |
| expected_innings | +0.364 | │ |
| umpire | +0.364 | ├ these **8 are the identical number** |
| pitch_count | +0.364 | │  (matchup_estimate × 1.0) — internal corr = **1.000** |
| pitch_mix | +0.364 | │ |
| bullpen_leash | +0.364 | │ |
| weather | +0.364 | │ |
| catcher_framing | +0.364 | ┘ |
| pitcher_recent_form | +0.294 | distinct; corr 0.892 with matchup |
| lineup_strength | +0.363 | distinct; corr 0.981 with matchup |

Look at the projection code (`model/projection.py`): components 1, 3, 5, 6, 7, 8, 9, 10 are
all `matchup_estimate × factor`, where `factor` is **1.0 whenever its data is neutral**
(and even with live data — umpire/mix/weather/catcher are *small* multipliers near 1.0, so
they stay ~perfectly correlated with the matchup estimate). Only **recent_form** (mean of
recent starts) and **lineup** (log5 vs the lineup K% instead of the team K%) are structurally
distinct — and even they correlate 0.89 and 0.98 with the matchup estimate.

## What this means for weight optimization

1. **It is a ~2-3 dimensional problem, not 10.** The 8 matchup-family weights are
   **unidentifiable** — any allocation among them that preserves their sum produces the
   *identical* projection. An optimizer's solution space is degenerate.
2. **Regularization toward the priors is mandatory, not optional** — it is the only thing
   that picks a unique, sensible point in that degenerate space.
3. **The upside is structurally small.** All you can actually tune is the balance between
   (matchup total) / (recent_form) / (lineup), and those three signals are themselves
   0.89-0.98 correlated — so even that lever has little leverage over the output.

This is a strong prior that a fitted weight set will land close to the expert priors and
beat them, if at all, by a tiny OOS margin — consistent with the archetype and group
results. It does **not** mean don't try; it means calibrate expectations and let the OOS
gate decide.

## Recommended path (Steps 2-3, if pursued)

- **Fit:** since λ = Σ wᵢ·estimateᵢ is linear, use **non-negative least squares + ridge
  toward the current priors**, sum-to-1 (convex, exact). Skip coordinate descent and
  Bayesian optimization — they are heuristics for a problem that is already convex, and
  BO is the wrong tool in a collinear 10-dim simplex.
- **Gate:** OOS by season (train 2015-22, val 23, test 24-25). Adopt only if it beats the
  priors OOS by a margin that survives — same discipline as the calibration validator and
  the group gate.
- **Ship:** behind a JSON-weights flag loaded **through** `ComponentWeights` (so the
  sum-to-1 validator still guards it), default = priors, mirroring `PROB_SHRINKAGE`.

## Caveat before an actual fit

This offline reconstruction's blended MAE is **1.86** vs the live pipeline's ~1.43 — the
reconstructed opponent windows are cruder and the minor-factor data is absent. That is fine
for the *structural* read (the collinearity is inherent to the projection formula, not the
reconstruction quality), but **input fidelity should be raised before the table is used for
an actual weight fit**, or the fitted weights will chase reconstruction noise.

## Step 2 confirmation — the fit lands on the priors (empirical)

Ran the recommended fit anyway to replace the prediction with a number: NNLS-style
convex fit (SLSQP), MAE + ridge-toward-priors, w≥0, Σw=1, on the 2024 backfill with a
temporal 70/30 split.

| | priors MAE | fitted MAE | gain |
|---|---|---|---|
| TRAIN (in-sample, best case) | 1.8544 | 1.8515 | **+0.0029** |
| TEST (out-of-sample) | 1.8808 | 1.8806 | **+0.0002** |

Even **in-sample** the fit beats the expert priors by only 0.003 K; **out-of-sample by
0.0002 K** — i.e. nothing. The fitted weights confirm the mechanism: all eight
matchup-family weights moved by the *identical* +0.007 (ridge pinned them to their prior
ratios because they are unidentifiable — only their sum, 0.69 → 0.75, is determined), and
the sole real change was trading recent_form (0.22 → 0.09) for lineup (0.09 → 0.16), which
changed MAE by ~0. **Verdict: weight optimization is confirmed low/no-EV and will not be
shipped.** Higher-leverage work: (1) make factors 5-10 *actually distinct* by feeding real
umpire / pitch-mix / weather / catcher data (Statcast is already on disk), so the ensemble
becomes genuinely multi-dimensional; (2) accumulate graded CLV — the real scoreboard.
