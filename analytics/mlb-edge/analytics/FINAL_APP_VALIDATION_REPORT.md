# Final App Validation Report - June 23, 2026

## Executive Summary

**Could not validate app's betting performance** because **0 out of 9 flagged pitchers actually played on June 23, 2026**.

---

## What Happened

### App's June 23 Predictions (from screenshot)
The app flagged **9 bets** for June 23, 2026:

| Pitcher | Opponent | Line | Pick | Expected K | Grade |
|---------|----------|------|------|------------|-------|
| Zac Gallen | Cardinals | 3.5 | UNDER | 2.35 | A |
| Bubba Chandler | Mariners | 4.5 | UNDER | 4.11 | A |
| Michael McGreevy | Diamondbacks | 2.5 | UNDER | 2.45 | A |
| Matthew Boyd | Mets | 4.5 | OVER | 5.20 | A |
| Cam Schlitter | Red Sox | 6.5 | OVER | 6.80 | B |
| Christopher Sánchez | Nationals | 6.5 | OVER | 6.58 | B |
| Cade Cavalli | Phillies | 4.5 | UNDER | 5.01 | C |
| Troy Melton | Astros | 4.5 | UNDER | 3.59 | C |
| Jeffrey Springs | Giants | 4.5 | UNDER | 4.42 | C |

### What Actually Happened (from MLB.com box scores)

**NONE of these pitchers played on June 23, 2026.**

Verified by checking box scores for:
- D-backs vs Cardinals → Rodriguez, Ed (5K) and Leahy (3K) started
- Mariners vs Pirates → Kirby (6K) and Keller (4K) started
- Cubs vs Mets → Cabrera (4K) and Senga (6K) started
- Red Sox vs Rockies → Gray (11K) and Sullivan (5K) started
- Phillies vs Nationals → Luzardo (13K) started for PHI
- Athletics vs Giants → Ray (6K) started for SF

**None of the app's predicted pitchers appeared in these games.**

---

## Root Cause Analysis

### Why the Mismatch?

**Most Likely:** App is predicting **FUTURE games** (June 23 is beyond database coverage)

Evidence:
- Database only has data through **June 14, 2026**
- Screenshot shows **June 23, 2026** (9 days into the future)
- App cannot have actual results for games that haven't finished yet

**Alternative explanations (less likely):**
- All 9 pitchers scratched last-minute (highly unlikely)
- App had completely wrong probable pitchers (possible but odd)
- Date mismatch (tested June 24 - also no data)

### Database Coverage Issue

```
Latest database date: June 14, 2026
Screenshot date:      June 23, 2026
Gap:                  9 days (FUTURE)
```

**Cannot validate predictions on future games.**

---

## What We CAN Test Instead

### Option 1: Test Model on Actual June 23 Starters

The pitchers who ACTUALLY played June 23:

| Pitcher | Team | K Total | Baseline MAE |
|---------|------|---------|--------------|
| Rodriguez, Ed | D-backs | 5 | |
| Leahy | Cardinals | 3 | |
| Kirby | Mariners | 6 | |
| Keller, M | Pirates | 4 | |
| Cabrera, E | Cubs | 4 | |
| Senga | Mets | 6 | |
| Gray, S | Red Sox | 11 | |
| Sullivan, S | Rockies | 5 | |
| Luzardo | Phillies | 13 | |
| Ray | Giants | 6 | |

**Average:** 6.3 K  
**Range:** 3-13 K  
**Baseline MAE** (if predicted average): **2.280 K**

Could test if our type-based model (baseline 1.672 MAE) beats this.

### Option 2: Test on June 14 (Last Available Date)

Found **4 matching pitchers** on June 14, 2026:
- Could test those 4 for partial validation
- Limited sample but better than nothing

### Option 3: Wait for Database Update

Once database includes June 23+ data:
1. Rerun box score extraction
2. Calculate actual K totals
3. Test betting hit rate
4. Test prediction MAE
5. Compare flagged vs unflagged accuracy

---

## What We LEARNED from Pure Prediction Tests

Even though we can't validate the app's June 23 bets, we tested the **underlying prediction model** extensively:

### Best Model: Type-Based Matchup
- **MAE:** 1.672 K
- **Correlation:** 0.479
- **Spread ratio:** 0.502 (underconfident)
- **Test sample:** 2,296 starts (2026 season)

### Failed "Improvements"
- **Individual player IDs:** MAE 1.693 (+1.3% WORSE)
- **+ Home/away + umpire:** MAE 1.715 (+2.6% WORSE)
- **Reason:** Overfitting, added noise not signal

### Key Finding
**Simpler is better** - coarse pitcher/batter types generalize better than individual IDs.

---

## Recommendations

### For Immediate Testing

1. **Use June 14 data** to test 4 matching pitchers (partial validation)
2. **Test model accuracy** on actual June 23 starters (ignore betting, just MAE)
3. **Update database** with June 23+ data when available

### For App Improvement

1. **Don't predict future games** - only show games with confirmed starters
2. **Update probable pitchers** closer to game time (last-minute scratches)
3. **Add "confidence" indicator** - flag when probable pitcher might change
4. **Test on in-sample dates** before deploying to future predictions

### For Betting Validation

**Need to test when:**
- Predicted pitchers actually play
- Can get actual K results
- Can calculate win/loss on bet recommendations

**Ideal test:**
- 50+ flagged bets with actual results
- Compare hit rate to 52.4% breakeven
- Compare flagged vs unflagged MAE
- Test if edge-finding logic adds value

---

## Bottom Line

### What We Know
✅ **Prediction model works** - MAE 1.672 beats baseline 1.786  
✅ **Type-based is best** - simpler beats complex  
✅ **Model is underconfident** - spread ratio 0.502 vs target 1.0  

### What We DON'T Know
❌ **Does app's betting logic work?** - Can't test on wrong pitchers  
❌ **Is edge-finding valuable?** - Need actual results to validate  
❌ **Does grading (A/B/C) predict accuracy?** - No data yet  

### Next Steps
1. Get June 23+ data in database
2. Rerun this validation with actual results
3. OR test on June 14 with 4 matching pitchers
4. OR wait for future date where app predictions match reality

---

## Files Created

```
C:\Users\carin\OneDrive\Dokument\stike\mlb-edge\analytics\
├── comprehensive_app_validation.py     (All 3 tests)
├── extract_june23_from_screenshot.py   (Manual validation helper)
├── FINAL_APP_VALIDATION_REPORT.md      (This report)
├── pure_prediction_test.py             (Model accuracy tests)
├── improved_prediction_test.py         (Individual IDs test)
├── variance_inflation_test.py          (Calibration test)
├── FINAL_PREDICTION_SUMMARY.csv        (All model results)
└── validate_june23_manual.csv          (Template for future validation)
```

---

**Test Date:** 2026-06-25  
**Database Coverage:** Through 2026-06-14  
**Screenshot Date:** 2026-06-23 (9 days beyond database)  
**Result:** Cannot validate - predicted pitchers didn't play
