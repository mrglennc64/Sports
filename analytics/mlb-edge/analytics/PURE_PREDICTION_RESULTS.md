# Pure Prediction Test Results (NO BETTING CONTEXT)

**Date**: 2026-06-25  
**Test**: MLB Strikeout Predictions  
**Train**: 2024-2025 seasons  
**Test**: 2026 season  
**N**: 2,296 pitcher starts

---

## Key Finding: MODEL IS UNDERCONFIDENT

Your predictions are **too compressed** - they don't spread widely enough compared to actual outcomes.

```
Ratio of spread (Predictions vs Actuals): 0.50

This means:
- Actual strikeout totals vary 2× more than your predictions
- You're being too conservative/regressing too hard to the mean
- Predictions cluster around 4-5 K when actuals span 0-15 K
```

---

## Overall Accuracy Metrics

| Metric | Value | Interpretation |
|--------|-------|----------------|
| **MAE** | 1.672 | Average miss of ~1.7 strikeouts per start |
| **RMSE** | 2.083 | Penalizing big misses, still reasonable |
| **Correlation** | 0.479 | Moderate positive relationship (0-1 scale) |
| **Calibration Slope** | 0.241 | Severely underconfident (should be 1.0) |
| **Overall Bias** | +0.234 | Slight overprediction on average |

### Comparison to Baseline

| Model | MAE | RMSE | Correlation |
|-------|-----|------|-------------|
| League average (dumb baseline) | 1.786 | 2.227 | 0.346 |
| **Your matchup model** | **1.672** | **2.083** | **0.479** |
| **Improvement** | **-6.4%** | **-6.5%** | **+38.4%** |

✅ You beat the league-average baseline on all metrics  
⚠️ But improvement is modest (~6% MAE reduction)

---

## Error Distribution

Your prediction errors (predicted - actual):

| Percentile | Error |
|------------|-------|
| 10th | -2.49 (underpredicted by 2.5 K) |
| 25th | -1.07 |
| **Median** | **+0.38** |
| 75th | +1.70 |
| 90th | +2.74 (overpredicted by 2.7 K) |

**Absolute errors:**
- 50% of starts: within 1.42 strikeouts
- 75% of starts: within 2.39 strikeouts
- 90% of starts: within 3.41 strikeouts

---

## Calibration Analysis

### By Prediction Level

When you predict different strikeout totals, how accurate are you?

| Predicted Range | N | Mean Pred | Mean Actual | Bias |
|-----------------|---|-----------|-------------|------|
| 2-3 K | 143 | 2.78 | 2.46 | +0.32 |
| 3-4 K | 337 | 3.58 | 3.26 | +0.32 |
| 4-5 K | 806 | 4.51 | 4.41 | +0.10 ✅ |
| 5-6 K | 599 | 5.47 | 5.25 | +0.22 |
| 6-7 K | 288 | 6.42 | 6.04 | +0.38 |
| 7-8 K | 108 | 7.38 | 6.90 | +0.48 |
| 8-9 K | 12 | 8.24 | 7.33 | +0.90 ⚠️ |

**Pattern**: Consistent slight overprediction across all levels, getting worse at high-K predictions.

### By Decile (Ordered by Prediction)

Do your highest predictions actually correspond to highest outcomes?

| Decile | Mean Pred | Mean Actual | Difference |
|--------|-----------|-------------|------------|
| Bottom 10% | 2.93 | 2.56 | +0.37 |
| 2 | 3.67 | 3.39 | +0.28 |
| 3 | 4.12 | 4.01 | +0.11 |
| 4 | 4.41 | 4.37 | +0.04 ✅ |
| 5 | 4.69 | 4.64 | +0.06 ✅ |
| 6 | 5.00 | 4.77 | +0.23 |
| 7 | 5.30 | 5.13 | +0.18 |
| 8 | 5.66 | 5.31 | +0.35 |
| 9 | 6.15 | 6.04 | +0.11 |
| **Top 10%** | **7.11** | **6.50** | **+0.61 ⚠️** |

✅ Good ranking (higher predictions → higher actuals)  
⚠️ But consistently overpredicting, especially at extremes

---

## Underconfidence Problem

```
Standard Deviation:
  Your predictions: 1.18
  Actual outcomes:  2.36
  
  Ratio: 0.50 (should be close to 1.0 for well-calibrated)
```

**What this means:**
- Actuals have 2× the variance of your predictions
- You're compressing everything toward the mean too aggressively
- Empirical Bayes shrinkage (SHRINK=200) may be too strong

**Potential fix:**
- Reduce SHRINK parameter from 200 → 100 or 50
- Use less aggressive regression to the mean
- Allow more extreme predictions when sample size supports it

---

## Implications

### For Prediction Accuracy
1. ✅ Model beats baseline by ~6%
2. ✅ Directionally correct (r=0.479)
3. ⚠️ Underconfident (spread ratio 0.50)
4. ⚠️ Slight overprediction bias (+0.23 K)

### For Betting (NOT tested here, but...)
- If odds were perfectly efficient, your MAE=1.67 would not overcome juice
- The 0.479 correlation suggests SOME predictive power
- But underconfidence means you're not differentiating enough between good/bad bets
- Real test is: does your model disagreement with OPENING line predict CLOSING line movement? (That's the CLV test you already have)

---

## Next Steps to Improve Pure Prediction

1. **Reduce shrinkage**: Try SHRINK=100, 50, or adaptive by sample size
2. **Add features**: 
   - Recent form (L5 starts)
   - Home/away splits
   - Umpire K-zone
   - Weather/park factors
3. **Use full pitcher identity** not just type (you have this in the code but not tested here)
4. **Validate calibration**: Predictions should match actuals in each bucket
5. **Test on different samples**: Do metrics hold for different pitcher tiers? (aces vs #5 starters)

---

## How These Tests Differ From Your Existing Tests

**Existing tests** (backtest_matchup.py, metrics.py):
- Mix prediction accuracy with betting decisions
- Include odds, juice, ROI, hit rate
- Answer: "Can we make money?"

**These tests** (pure_prediction_test.py, prediction_diagnostics.py):
- ONLY prediction quality
- No odds, no bookmakers, no profitability
- Answer: "How accurate are our forecasts?"

**Both are valuable:**
- Pure prediction → build the best model
- Betting tests → find if/when to bet it

You can have a great pure prediction model that still loses to efficient markets (see: your tennis/horse models). Or a mediocre prediction that wins if you find market inefficiencies.

---

*Generated: 2026-06-25*  
*Scripts: pure_prediction_test.py, prediction_diagnostics.py*
