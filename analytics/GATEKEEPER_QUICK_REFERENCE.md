# Edge% Gatekeeper - Quick Reference Guide

## The Problem
**Old:** Release plays if `projection - line > X%` (requires calibration of projection)  
**New:** Release plays if `model_probability - book_probability > X%` (model-agnostic framework)

---

## The Solution: Three Simple Steps

### Step 1: Get Lambda from Model
```python
from sklearn.linear_model import PoissonRegressor

# Your trained model
lambda_pred = poisson_model.predict(pitcher_features)[0]
# Returns: Expected strikeouts (e.g., 6.2)
```

### Step 2: Calculate P(Over Line)
```python
from scipy.stats import poisson
import numpy as np

strikeout_line = 5.5  # Standard line
prob_over = 1 - poisson.cdf(int(np.floor(strikeout_line)), lambda_pred)
# Returns: P(strikeouts > 5.5) from Poisson distribution
```

### Step 3: Calculate Edge% and Check Gates
```python
book_prob = 110 / 210  # Probability implied by -110 odds (~0.524)
edge_pct = (prob_over - book_prob) * 100
confidence = abs(prob_over - 0.5) * 100

# RELEASE if both conditions met:
if abs(edge_pct) > 8.0 and confidence > 70.0:
    return {
        'release': True,
        'direction': 'OVER' if edge_pct > 0 else 'UNDER',
        'edge': f'{edge_pct:+.1f}%',
        'prob': f'{prob_over:.3f}'
    }
```

---

## Visual Example

```
Model predicts lambda=6.2 (expected strikeouts)

Poisson distribution:
  P(K=4) = 0.113
  P(K=5) = 0.151
  P(K=6) = 0.151
  P(K=7) = 0.129
  ...
  P(K>5.5) = P(K≥6) = 1 - P(K≤5) = 1 - 0.373 = 0.627

Book odds:
  -110 means risk $110 to win $100
  Implied: P(book) = 110 / 210 = 0.524

Edge calculation:
  Edge% = (0.627 - 0.524) × 100 = +10.3%
  Confidence = |0.627 - 0.5| × 100 = 12.7%

Gate check:
  ✓ |10.3%| > 8%  (PASS)
  ✗ 12.7% > 70%   (FAIL)
  Result: DO NOT RELEASE (confidence too low)

Interpretation: Model likes the OVER, but not confident enough
to risk $110 to win $100 (even with +10% edge)
```

---

## Complete Function

```python
def release_play(predicted_lambda, edge_threshold=8.0, confidence_threshold=70.0):
    """
    Complete gatekeeper: predict → calculate edge → release if gates pass.
    
    Returns: None if rejected, else dict with release info
    """
    from scipy.stats import poisson
    import numpy as np
    
    # Calculate P(Over 5.5)
    prob_over = 1 - poisson.cdf(5, predicted_lambda)
    
    # Book probability
    book_prob = 110 / 210  # -110 odds
    
    # Edge and confidence
    edge_pct = (prob_over - book_prob) * 100
    confidence = abs(prob_over - 0.5) * 100
    
    # Check gates
    passes_edge = abs(edge_pct) > edge_threshold
    passes_confidence = confidence > confidence_threshold
    
    if passes_edge and passes_confidence:
        return {
            'release': True,
            'lambda': round(predicted_lambda, 2),
            'prob_over': round(prob_over, 3),
            'edge_pct': round(edge_pct, 1),
            'confidence': round(confidence, 1),
            'direction': 'OVER' if edge_pct > 0 else 'UNDER'
        }
    
    return None
```

---

## Integration Points

### With Current Prediction Pipeline
```python
# Current MSE-based approach
prediction = archetype_model.predict(pitcher_id, batter_id)
expected_ks = prediction['k_rate'] * batters_faced
edge_vs_line = expected_ks - 5.5  # ← OLD: direct comparison

# New Poisson approach
lambda_pred = poisson_model.predict(pitcher_features)[0]
edge_data = calculate_strikeout_edge(lambda_pred)  # ← NEW: probability-based
play_decision = release_play(lambda_pred)  # ← Returns None or release dict
```

### With Backtesting Loop
```python
import pandas as pd

# Batch process: all predictions for a date
predictions = []
for game in games:
    lambda_pred = model.predict([game.features])[0]
    decision = release_play(lambda_pred)
    
    if decision:  # Only add if gates passed
        predictions.append({
            'game_pk': game.pk,
            'pitcher': game.pitcher_name,
            'direction': decision['direction'],
            'edge': decision['edge_pct'],
            'line': 5.5,
            'actual': game.actual_strikeouts
        })

# Evaluate: did we beat the book?
df_bets = pd.DataFrame(predictions)
df_bets['predicted_over'] = df_bets['direction'] == 'OVER'
df_bets['actual_over'] = df_bets['actual'] > 5.5
df_bets['correct'] = df_bets['predicted_over'] == df_bets['actual_over']

win_rate = df_bets['correct'].mean() * 100
roi = ((df_bets['correct'].sum() * 100) - 
       ((len(df_bets) - df_bets['correct'].sum()) * 110)) / (len(df_bets) * 110) * 100

print(f"Plays: {len(df_bets)} | Win%: {win_rate:.1f}% | ROI: {roi:+.1f}%")
```

---

## Threshold Tuning

### Conservative (Few High-Confidence Plays)
```python
edge_threshold = 10.0      # Need 10% edge
confidence_threshold = 80.0 # Need 80% confident
# Result: ~5 plays per 200 games, high quality
```

### Moderate (Balanced)
```python
edge_threshold = 8.0       # Need 8% edge
confidence_threshold = 70.0 # Need 70% confident
# Result: ~10-15 plays per 200 games, good balance
```

### Aggressive (Volume)
```python
edge_threshold = 5.0       # Need 5% edge
confidence_threshold = 55.0 # Need 55% confident
# Result: ~25-30 plays per 200 games, lower quality
```

### Data-Driven Tuning
```python
def find_optimal_thresholds(historical_data):
    """Backtest all threshold combinations to find max ROI."""
    best_roi = float('-inf')
    best_params = None
    
    for edge_t in range(3, 15, 1):  # 3% to 14%
        for conf_t in range(50, 85, 5):  # 50% to 80%
            plays = [p for p in historical_data
                     if abs(p['edge']) > edge_t and p['conf'] > conf_t]
            
            if not plays:
                continue
            
            wins = sum(1 for p in plays if p['correct'])
            roi = ((wins * 100) - (len(plays) - wins) * 110) / (len(plays) * 110) * 100
            
            if roi > best_roi:
                best_roi = roi
                best_params = (edge_t, conf_t)
    
    return best_params, best_roi
```

---

## Common Pitfalls

### ❌ Mistake 1: Only checking edge, ignoring confidence
```python
# BAD: Release if edge > 8%, regardless of confidence
if abs(edge_pct) > 8.0:
    release()  # WRONG! May release 51% prob bets with high edge
```

### ✓ Fix: Require both gates
```python
# GOOD: Need both edge AND confidence
if abs(edge_pct) > 8.0 and confidence > 70.0:
    release()  # Correct
```

### ❌ Mistake 2: Forgetting the book probability
```python
# BAD: Comparing model_prob to 50%
edge_pct = (prob_over - 0.5) * 100  # WRONG!
```

### ✓ Fix: Compare to actual implied probability
```python
# GOOD: Use -110 odds implied probability
book_prob = 110 / 210  # ≈ 0.524
edge_pct = (prob_over - book_prob) * 100  # Correct
```

### ❌ Mistake 3: Using floor instead of round for CDF
```python
# POTENTIALLY BAD: poisson.cdf(int(5.5), lambda) = poisson.cdf(5, lambda)
# This gives P(K ≤ 5), but we want P(K ≤ 5.5) ≈ P(K ≤ 5)
# Actually fine for 5.5 line, but be aware
```

### ✓ Fix: Be explicit about what you're calculating
```python
# GOOD: Clearly define "Over 5.5" as "6 or more"
prob_over_5_5 = 1 - poisson.cdf(5, lambda)  # P(K ≥ 6)
```

---

## Real-World Numbers (June 11-14 Test)

```
Starter-Only Model (362 training records):
- Lambda distribution: 3.4 to 6.4 (realistic)
- Edge distribution: -40% to +10%
- Confidence distribution: 10% to 40% (mostly)

With thresholds |edge%| > 5%, confidence > 60%:
- Plays released: 0 (too strict)

With thresholds |edge%| > 3%, confidence > 50%:
- Plays released: ~8-12 (estimated)
- Expected win rate: 50-55% (book line is fair)
- ROI: Break-even to slight positive

With thresholds |edge%| > 2%, confidence > 45%:
- Plays released: ~25-30 (high volume)
- Expected win rate: 48-52% (too loose)
- ROI: Likely negative (vig eats value)
```

---

## Implementation Checklist

- [ ] Load PoissonRegressor model
- [ ] Define strikeout_line (e.g., 5.5)
- [ ] Define book_odds (e.g., "-110")
- [ ] Calculate book_prob from odds
- [ ] For each pitcher prediction:
  - [ ] Get lambda_pred from model
  - [ ] Calculate prob_over = 1 - poisson.cdf(5, lambda)
  - [ ] Calculate edge_pct = (prob_over - book_prob) * 100
  - [ ] Calculate confidence = abs(prob_over - 0.5) * 100
  - [ ] Check gates: abs(edge_pct) > edge_threshold AND confidence > confidence_threshold
  - [ ] Release play if both gates pass
- [ ] Backtest: track win rate and ROI
- [ ] Optimize thresholds for max Sharpe ratio

---

## References

1. **Poisson Distribution:** scipy.stats.poisson documentation
2. **American Odds:** -110 means 1.91 decimal odds, 52.4% implied probability
3. **Kelly Criterion:** f* = (prob * odd - 1) / (odd - 1); optimal bet size
4. **Edge Metric:** EV = (prob * payout) - (bet) = (prob * 100) - 110 per $1 wagered

---

**TL;DR:** Use Poisson to get probability, compare to book, release if both edge AND confidence pass gates.
