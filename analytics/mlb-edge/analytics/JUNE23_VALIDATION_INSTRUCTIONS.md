# June 23, 2026 App Predictions Validation

## Screenshot Data Captured

Your app predicted 15 pitchers on 2026-06-23:

### Flagged Bets (9 total - marked with grades A/B/C)
| Pitcher | Opponent | Line | Pick | Exp K | Grade |
|---------|----------|------|------|-------|-------|
| Zac Gallen | St. Louis Cardinals | 3.5 | UNDER | 2.35 | A |
| Bubba Chandler | Seattle Mariners | 4.5 | UNDER | 4.11 | A |
| Michael McGreevy | Arizona Diamondbacks | 2.5 | UNDER | 2.45 | A |
| Matthew Boyd | New York Mets | 4.5 | OVER | 5.20 | A |
| Cam Schlitter | Boston Red Sox | 6.5 | OVER | 6.80 | B |
| Christopher Sánchez | Washington Nationals | 6.5 | OVER | 6.58 | B |
| Cade Cavalli | Philadelphia Phillies | 4.5 | UNDER | 5.01 | C |
| Troy Melton | Houston Astros | 4.5 | UNDER | 3.59 | C |
| Jeffrey Springs | San Francisco Giants | 4.5 | UNDER | 4.42 | C |

### Unflagged (6 total - no betting recommendation)
| Pitcher | Opponent | Line | Pick | Exp K |
|---------|----------|------|------|-------|
| Kevin Gausman | Texas Rangers | 6.5 | OVER | 6.05 |
| MacKenzie Gore | Toronto Blue Jays | 4.5 | UNDER | 5.26 |
| Freddy Peralta | Chicago Cubs | 5.5 | UNDER | 4.54 |
| Tatuya Imai | Detroit Tigers | 5.5 | UNDER | 5.06 |
| Connelly Early | New York Yankees | 5.5 | OVER | 6.13 |
| Landen Roupp | Athletics | 6.5 | UNDER | 5.83 |

## How to Validate

### Step 1: Get Actual Results

Go to **Baseball Reference** (baseball-reference.com) or **MLB.com** and look up June 23, 2026 games.

For each pitcher, record:
- Actual strikeouts pitched
- Batters faced (optional)
- IP (innings pitched, optional)

### Step 2: Fill in the CSV

Open `validate_june23_manual.csv` and fill in the `Actual_KS` column.

### Step 3: Run the Validation

```bash
cd mlb-edge/analytics
.venv/Scripts/python.exe validate_june23_results.py
```

## What the Validation Will Show

### 1. App Betting Performance
- Win/Loss record on the 9 flagged bets
- Hit rate (need 52.4%+ to beat -110 juice)
- Whether app found profitable betting spots

### 2. Pure Prediction Accuracy  
- MAE (mean absolute error) for all 15 pitchers
- MAE for flagged vs unflagged separately
- Whether flagged games were actually MORE predictable

### 3. Comparison to Baseline
- Baseline model MAE: **1.672 K** (from 2,296 test starts)
- June 23 MAE: will show if this was an easier/harder day

## Two Different Questions

**App Betting Approach:**
- Uses expected value, Kelly criterion, odds analysis
- Flags bets with perceived edge
- Success metric: **Win rate > 52.4%**

**Pure Prediction Approach:**
- Just forecasts strikeouts, ignores betting
- No edge calculation, no odds
- Success metric: **Low MAE (close to 1.67)**

## Possible Outcomes

1. **Good betting, good predictions** ✅✅
   - Hit rate > 52.4% AND MAE < 1.8
   - App working as intended

2. **Good betting, bad predictions** ✅❌
   - Hit rate > 52.4% BUT MAE > 2.0
   - Got lucky, or line-relative prediction works even with absolute error

3. **Bad betting, good predictions** ❌✅
   - Hit rate < 52.4% BUT MAE < 1.8
   - Accurate forecasts but no edge vs the line

4. **Bad betting, bad predictions** ❌❌
   - Hit rate < 52.4% AND MAE > 2.0
   - Rough day for the model

## Files Created

- `validate_june23_manual.csv` - Fill this in with actual results
- `validate_june23_results.py` - Run this after filling CSV
- `app_vs_prediction_test.py` - Attempted auto-validation (no data for June 23 yet)

## Database Limitation

The `baseball.duckdb` file only has data through **June 14, 2026**. That's why we can't auto-validate June 23 yet. You'll need to:

1. Either manually enter results from Baseball Reference, OR
2. Wait until June raw data is loaded into the database

## Expected Baseline

From our testing:
- **Type-based model MAE**: 1.672 K
- **Correlation**: 0.479
- **Spread ratio**: 0.502 (underconfident)

A good June 23 would be:
- MAE around 1.5-1.9 (normal variance)
- Flagged bets hit rate 55%+ (would indicate real edge)
- Flagged MAE < unflagged MAE (model selecting predictable games)
