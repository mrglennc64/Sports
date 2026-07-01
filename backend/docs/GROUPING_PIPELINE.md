# Grouping Pipeline — Group-vs-Group Strikeout Prior

End-to-end design for the offline grouping engine that turns 10 years of
play-by-play into a **group-vs-group strikeout prior**, and the **out-of-sample
(OOS) gate** that decides whether that prior is ever allowed into production.

> Bottom line up front: the prior ships **only if it beats a naive baseline out of
> sample**. This is the same discipline that DISABLED the earlier archetype model
> (archetype MAE **1.57** vs naive baseline **1.43** — worse, so it was turned off).
> Building the model is not evidence it works. The OOS scorer is the evidence.

This package (`app/grouping/*`) is **offline tooling**. The live API never imports
it; its heavy dependencies (`pybaseball`, `scikit-learn`, `pyarrow`) live in
`requirements-grouping.txt`, NOT in `requirements.txt`, and are not installed on the
production server.

---

## 1. Data sources

### Retrosheet (the clustering + outcome foundation)
- Per-season parsed CSV bundles: `https://www.retrosheet.org/downloads/{year}/{year}csvs.zip`
  → `{year}plays.csv` (~110 MB, ~195k plays/season). No Chadwick C-tool needed.
- Local store: `C:\strike-data\retrosheet\{year}\{year}plays.csv` (override with
  `STRIKE_DATA_DIR`).
- Gives event outcomes (`pa`, `k`, `walk`, batted-ball type GB/FB/LD) and a
  pitch-**result** string (`C/S/B/F/X`), plus handedness for platoon splits.
- Player ids are **Retrosheet ids** (e.g. `alfoa001`), not MLBAM ids.
- Does **NOT** have: pitch types, release/exit velocity, launch angle.

### Statcast / Baseball Savant (the pitch-physics layer)
- Pulled via `pybaseball` (`app/grouping/statcast.py`), 2015+. ~700k pitches/season,
  rate-limited — a 10-year pull is a long batch job, cached to Parquet.
- Adds pitch types (fastball/breaking/offspeed buckets), whiff-by-type, chase rate,
  velocity, exit velocity, launch angle, hard-hit rate.
- Player ids are **MLBAM ids** (e.g. `545361`), NOT Retrosheet ids.

### ID mismatch — the crosswalk (important)
Retrosheet ids and MLBAM ids are **different namespaces**. Joining the Statcast
physics features onto the Retrosheet feature/outcome rows requires a **crosswalk**:

- Use `pybaseball.playerid_lookup` / the Chadwick `people` register (the
  `key_retro` ↔ `key_mlbam` mapping), or `pybaseball.playerid_reverse_lookup`.
- Join on `(key_retro, season)` → `(key_mlbam, season)` before merging feature tables.
- A player without a crosswalk row drops out of the physics-augmented feature set;
  the Retrosheet-only features still cluster him (graceful degradation).

The grouping store keeps **Retrosheet ids** as the canonical key (because the
outcome and matrix layers are Retrosheet-driven); Statcast is joined IN via the
crosswalk, not the other way around.

---

## 2. Pipeline stages

```
Retrosheet plays.csv ─┐
                      ├─► feature engineering ─► clustering ─► GROUPS ─┐
Statcast (crosswalk) ─┘   (app/grouping/        (KMeans +     (pitcher/ │
                           features.py +         stability)    batter)  │
                           statcast.py)                                 │
                                                                        ▼
                              group-vs-group strikeout MATRIX  ◄────────┘
                              [pitcher_group, batter_group, n_pa,
                               k_rate_raw, k_rate_shrunk, global_rate]
                                          │
                                          ▼
                              expected_ks_prior (app/grouping/group_prior.py)
                                          │
                                          ▼
                              ┌─► OOS GATE: prior_mae vs baseline_mae ◄─┐
                              │   (evaluate_prior_oos)                  │
                              ▼                                         │
                       beats baseline? ── no ──► DO NOT SHIP (disabled) ┘
                              │
                             yes
                              ▼
                       wire into production
```

### 2a. Feature engineering — `app/grouping/features.py`
Per `(player_id, season)` behavioural vectors from Retrosheet: K rate, BB rate,
GB/FB/LD rates, swinging-strike rate, called-strike rate, first-pitch-strike rate,
put-away rate, K-rate vs L/R, pitches per PA. Thin samples (`< MIN_PA = 50`)
dropped. Statcast features (`app/grouping/statcast.py`) joined via the crosswalk.

### 2b. Clustering → GROUPS
KMeans (+ stability selection) over the feature vectors clusters pitchers and
batters separately into **groups** (deliberately NOT called "archetypes"). Output:
`C:\strike-data\groups\{pitcher,batter}_groups.parquet` with columns
`(player_id, season, group)` — group membership is **per season** (a player can
move groups year to year).

### 2c. Group-vs-group matrix (parallel task)
`C:\strike-data\groups\matchup_matrix.parquet`, columns:

| column          | meaning                                                        |
|-----------------|----------------------------------------------------------------|
| `pitcher_group` | pitcher cluster id                                             |
| `batter_group`  | batter cluster id                                             |
| `n_pa`          | PAs observed for this cell (TRAIN years)                       |
| `k_rate_raw`    | raw K/PA in the cell                                           |
| `k_rate_shrunk` | K/PA shrunk toward `global_rate` (empirical-Bayes; thin cells) |
| `global_rate`   | league-wide K/PA (stored on every row, redundantly)            |

Lookup contract: `matchup_k_rate(matrix, pgroup, bgroup) -> rate`. The matrix is
built from **TRAIN years only** to keep the OOS test honest.

### 2d. The prior — `app/grouping/group_prior.py`
`expected_ks_prior(pitcher_group, batter_lineup_groups, expected_bf, matrix)`:

```
mean_rate = mean over faced batters of matchup_k_rate(matrix, g_p, g_b)
lambda    = mean_rate * expected_bf            # default (scale_to_bf=True)
# or, with the EXACT batters faced and scale_to_bf=False:
lambda    = sum over faced batters of matchup_k_rate(matrix, g_p, g_b)
```

Fallbacks (never error, never silent zero):
- A missing/unknown **batter** group → that cell uses `global_rate` (per-cell, inside
  `matchup_k_rate`).
- A missing **pitcher** group or empty lineup → `global_rate * expected_bf`.

`player_group(groups_df, player_id, season)` does the exact `(player_id, season)`
join and returns `None` on a miss (driving the fallback).

---

## 3. The OOS gate — `evaluate_prior_oos(train_years, test_years)`

The gate that decides production-worthiness:

1. Build/load the matrix from **TRAIN years only** (no leakage).
2. For each pitcher **start** in the **TEST years** (reconstructed from Retrosheet:
   one `(gid, starter)` group = BF, actual Ks, ordered batters faced):
   - **prior** prediction: `expected_ks_prior(...)` using TRAIN-fit groups + matrix.
   - **baseline** prediction: naive `global_rate * BF` (the league rate — the bar to
     beat). An alternative baseline is the pitcher's own prior K/PA × BF.
   - **actual**: Ks that start.
3. Score `prior_mae` and `baseline_mae`; report
   `improvement = baseline_mae - prior_mae` (positive ⇒ prior better) and the
   `beats_baseline` boolean.

Returns: `{n, prior_mae, baseline_mae, improvement, beats_baseline, train_years,
test_years}`.

The scoring math (`expected_ks_prior`, `mae`, `score_predictions`) is **pure** and
unit-tested on synthetic arrays with no file I/O; the heavy loaders
(`load_matrix`, `load_groups`, `load_test_starts`) are separated so the math can be
verified independently of the data being present.

### Ship / no-ship rule
- `beats_baseline == True` (and by a margin that survives noise / re-runs across
  multiple test seasons) → candidate for wiring into the production strikeout model.
- `beats_baseline == False` → **disabled**, exactly like the archetype model
  (1.57 vs 1.43). We do not ship a model that loses out of sample.

---

## 4. File map

| path | role |
|------|------|
| `app/grouping/retrosheet.py` | Retrosheet download + schema validation |
| `app/grouping/features.py`   | Retrosheet → per-player feature vectors |
| `app/grouping/statcast.py`   | Statcast pull + physics features (crosswalk join) |
| `app/grouping/group_prior.py`| prior + `matchup_k_rate` + OOS gate (this doc's subject) |
| `tests/test_group_prior.py`  | synthetic unit tests for the prior + scoring math |
| `C:\strike-data\groups\matchup_matrix.parquet` | group-vs-group matrix (parallel task) |
| `C:\strike-data\groups\{pitcher,batter}_groups.parquet` | per-season group membership |
| `C:\strike-data\retrosheet\{year}\{year}plays.csv` | play-by-play |

---

## 5. RIGOROUS LEAK-FREE OOS VERDICT (2026-07-01)

The first OOS pass beat a *league-average* baseline by +0.21 MAE — but that bar is
trivial and the group membership for test years leaked (assigned from the test
season itself). Re-ran the gate correctly:

- **Train-only matrix** (2015–2023); **test** = 2024–2025 starts (n = 8,512 with a
  prior track record).
- **Membership = prior year** (a 2024 start uses the pitcher's/batters' latest
  pre-2024 group — what you'd actually know before the game). No leakage.
- **Strong baseline** = the pitcher's **own** prior-season K/PA × BF (the signal the
  live ensemble already uses at weight 0.22), not league average.

**MAE ladder (lower better):**

| predictor | MAE |
|---|---|
| league-avg × BF (weak) | 1.878 |
| pitcher's OWN prior rate × BF | 1.825 |
| group-vs-group prior | **1.788** |

- vs league-avg: **+0.090** ; vs own rate: **+0.037** (the bar that matters).

**Verdict: DO NOT SHIP (yet).** The group prior beats the pitcher's own rate only
by **+0.037 MAE** — marginal — and that edge comes almost entirely from *opponent*
(batter-group) information the production ensemble **already captures** (opponent K
profile, log5, weight 0.26). All three simple predictors (~1.79–1.88) are also far
worse than the ensemble's ~1.43 MAE, so the group prior is not competitive as a
standalone and is unlikely to add as a blended feature — the same conclusion that
disabled the archetype model. The OOS gate did its job: it stopped a redundant
signal from shipping on the strength of a misleading league-average comparison.

**Only thing that could change this:** sharper, higher-resolution groups. k=4 is
coarse (silhouette ≈ 0.12 → styles are a continuum, not clean clusters). Re-clustering
with the now-downloaded **Statcast pitch-physics features** (pitch types, whiff-by-type,
velo, exit velo) — joined via the Retrosheet↔MLBAM crosswalk — is the one experiment
with a chance of moving the number. Expected value is modest given this evidence.

---

## 6. Phase 2.5 experiment — add Statcast physics features (2026-07-01)

Hypothesis: the marginal Retrosheet-only result (+0.037 vs own rate) was limited by
coarse groups; joining Statcast pitch-physics features (pitch types, whiff-by-type,
velo, exit velo, launch angle) might sharpen the clusters and beat the pitcher's own
rate by a non-marginal margin.

Setup: crosswalk MLBAM↔Retrosheet (Chadwick register, `app/grouping/combined.py`) →
inner join on (retro_id, season) → **100% coverage** (6,719 pitcher- and 5,885
batter-seasons, zero NaN) → 24-feature vectors (12 Retrosheet + 12 Statcast) →
re-cluster → rebuild train-only matrix → same leak-free OOS gate.

**Result — the experiment FAILED (made it worse):**

| groups | silhouette (pitchers) | OOS improvement vs own rate |
|---|---|---|
| Retrosheet-only | 0.122 | +0.0374 |
| Retrosheet + Statcast | **0.086** | **+0.0174** |

Adding the physics features *lowered* cluster separation and *halved* the OOS edge.
The Statcast features are largely redundant with the Retrosheet behavioural ones
(Statcast whiff ≈ Retrosheet swinging-strike rate), so they added dimensionality/noise
to a k=4 partition of what is fundamentally a **continuum**, not clean clusters.

**Final verdict: group-vs-group is a confirmed dead end for strikeout prediction.**
Neither Retrosheet-only nor Statcast-enriched groups beat the pitcher's own prior rate
by a meaningful margin, and both are far worse than the production ensemble (~1.43 MAE
vs ~1.79–1.81 here). This is the third independent confirmation of the same finding
(archetype model 1.57 vs 1.43; Retrosheet groups +0.037; combined groups +0.017).
The pipeline is retained as a validated research asset and as the group features may
be useful elsewhere (e.g. opponent-context tagging), but it will NOT be wired into the
staking model. The honest lesson: pitcher/batter styles don't partition cleanly enough
for a group prior to out-resolve an individual's own rate.
