# Archetype Model Root Cause Diagnosis

## Executive Summary

The archetype model performs **38.6% WORSE** than simple global fallback:
- **Archetype**: MAE 1.85, correlation 0.457, betting accuracy 61.7%
- **Fallback**: MAE 1.33, correlation 0.643, betting accuracy 83.9%

**Root Cause**: Archetypes wash out pitcher-specific skill, replacing individual K-rates with broad archetype averages.

---

## Key Findings

### 1. Archetype Assignments Lose Signal

**Problem**: Archetypes group pitchers by style, not K-rate, creating heterogeneous clusters.

**Evidence**:
- Archetype 4 ("strikeout / power-velo"): 2026 K-rate range 26.2% to 39.8%
  - Jacob Misiorowski: 39.8% actual, assigned 28.1% archetype rate → -11.7% error
  - This single assignment error cost 2.7 strikeouts per game on average
  
- Archetype 3 ("hittable / fly-ball"): 2026 K-rate range 18.9% to 27.9%
  - 9% spread in K-rate within same archetype
  - Archetype avg 22.7% vs actual range → massive variance

**Signal Loss Metrics**:
- Only 20 of 146 backtest pitchers (13.7%) have 2026 season data for validation
- Among those 20:
  - Mean absolute K% difference: 2.82%
  - Correlation (archetype K% vs actual 2026 K%): 0.686
  - Worst case: 11.7% K-rate error (Jacob Misiorowski)

**Why This Happens**:
- Pitchers clustered on **style** (velocity, whiff%, chase%, GB%)
- NOT clustered on **outcome** (K-rate)
- A high-velo pitcher with 39.8% K-rate gets same archetype rate as average high-velo pitcher at 28.1%

### 2. Interaction Matrix Has No Sample Size Problems

**Finding**: ALL 42 cells have >4000 PAs, median 7204 PAs.
- Zero cells with < 1000 PAs
- Smallest cell: 3997 PAs (Archetype 4 vs Batter Type 6)
- This is **not** the problem

**Conclusion**: Sample sizes are sufficient. The issue is signal loss from clustering.

### 3. Archetype Method Underperforms Even When Available

**Critical Finding**: 
- 324 games used archetype method → MAE 1.85, Corr 0.457
- 93 games used fallback → MAE 1.33, Corr 0.643

**Fallback beats archetype by 28% in MAE and 41% in correlation.**

This means the archetype model is **actively harmful** compared to just using global averages.

### 4. Why Archetypes Fail

**The Flaw**:
1. Archetypes cluster pitchers on **how** they pitch (velo, whiff%, GB%)
2. But **outcome** (K-rate) varies widely within each archetype
3. When predicting strikeouts, we replace pitcher's actual K-rate with archetype average
4. This loses 3-12% of K-rate signal per pitcher

**Example**:
- **Spencer Strider**: Archetype 3 assigns 22.7% K-rate, actual 27.9% → -5.1% error
- **Shane Baz**: Archetype 3 assigns 22.7% K-rate, actual 18.9% → +3.9% error
- Both in same archetype, but 9% apart in actual skill

**Contrast with Fallback**:
- Fallback uses pitcher's **own K-rate** from prior games
- Direct measurement of actual skill
- Only regresses slightly toward league average
- Preserves pitcher-specific signal

---

## Why the Model Was Built This Way

**Original Intent**: Capture pitcher × batter interactions
- Theory: High-whiff pitchers do especially well vs high-chase batters
- Reality: Interaction signal is swamped by archetype signal loss

**What Actually Happens**:
1. Assign pitcher to archetype based on style → lose 3-12% K-rate signal
2. Assign batters to archetypes → lose batter-specific discipline signal
3. Look up 42-cell interaction matrix → regress both to broad averages
4. Net result: Worse than using pitcher's own historical K-rate

---

## Recommendations

### Immediate Fix
**Replace archetype model with pitcher-specific model:**
- Use pitcher's actual 2026 K-rate, not archetype average
- Apply batter lineup adjustment (vs RHB/LHB split or individual batter K-rates)
- Keep interaction effects if they add value AFTER preserving base rates

### Long-term Research
**Test if interactions add value over base rates:**
1. Baseline: Pitcher K-rate × Batter K-rate → prediction
2. Archetype interaction: Pitcher archetype × Batter archetype → residual
3. Compare MAE: Base vs Base+Interaction

**Hypothesis**: Interactions will not beat base rates because:
- Pitcher skill (own K-rate) >> style effects
- Batter discipline (own K-rate) >> archetype effects
- Efficient market already prices in obvious matchups

---

## Data Quality Issues Found

### Gamelogs Coverage Gap
- Gamelogs end June 12, 2026
- Backtest covers June 1-14, 2026
- Only 21 pitchers have full 2026 season data through June 12
- 86.3% of backtest pitchers lack 2026 validation data

### Archetype Clustering Timing
- Archetypes built on 2026 partial season (through June 12)
- Only 50+ PA threshold → excludes rookies and callups
- Many June 1-14 pitchers not yet clustered → fall back to global avg

---

## Bottom Line

**The archetype model fails because it replaces pitcher-specific skill (K-rate) with style-based archetypes that have 9-14% K-rate variance within clusters.**

**Fallback wins because it uses the pitcher's actual historical K-rate, which is a direct measurement of skill.**

**Fix: Use pitcher K-rate as base, add batter adjustments, test if archetype interactions improve over this baseline.**
