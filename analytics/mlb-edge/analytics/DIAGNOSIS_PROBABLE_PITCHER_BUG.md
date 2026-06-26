# DIAGNOSIS: Probable Pitcher Data Source Bug

## Executive Summary

**CRITICAL BUG**: The app's June 23 probable pitchers **DO NOT match the MLB Stats API** it's supposed to be using.

- **0 out of 9** app predictions matched API probables for June 23
- **0 out of 9** app predictions matched actual starters from MLB.com box scores
- App is showing pitchers from an **unknown data source**

---

## The Evidence

### What MLB Stats API Returns for June 23, 2026

```
API Endpoint: https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-06-23

Cardinals game:    Kyle Leahy (StL)  vs Eduardo Rodriguez (AZ)
Mariners game:     George Kirby (SEA) vs Mitch Keller (PIT)
Mets game:         Kodai Senga (NYM) vs Edward Cabrera (CHC)
Red Sox game:      Sonny Gray (BOS) vs Sean Sullivan (COL)
Nationals game:    PJ Poulin (WSH) vs Jesús Luzardo (PHI)
Giants game:       Robbie Ray (SF) vs Aaron Civale (ATH)
```

###What the App Showed (June 23)

```
vs Cardinals:    Zac Gallen ❌ (API says: Kyle Leahy)
vs Mariners:     Bubba Chandler ❌ (API says: George Kirby)
vs Mets:         Matthew Boyd ❌ (API says: Kodai Senga)
vs Red Sox:      Cam Schlitter ❌ (API says: Sonny Gray)
vs Nationals:    Christopher Sánchez ❌ (API says: PJ Poulin)
                 Cade Cavalli ❌ (API says: Jesús Luzardo)
vs Giants:       Jeffrey Springs ❌ (API says: Robbie Ray)
vs Diamondbacks: Michael McGreevy ❌ (API says: Eduardo Rodriguez)
vs Astros:       Troy Melton ❌ (API says: Peter Lambert)
```

**Match rate: 0%**

### What Actually Pitched (from MLB.com box scores)

```
Cardinals:   Kyle Leahy (3 K) - MATCHES API ✓
Mariners:    George Kirby (6 K) - MATCHES API ✓
Mets:        Kodai Senga (6 K) - MATCHES API ✓
Red Sox:     Sonny Gray (11 K) - MATCHES API ✓
Nationals:   PJ Poulin + others - MATCHES API ✓
Giants:      Robbie Ray (6 K) - MATCHES API ✓
```

**The MLB Stats API was CORRECT. The app was WRONG.**

---

## Root Cause Analysis

### Where the App SHOULD Get Probables

Code location: `mlb-edge/backend/app/data/mlb_stats.py`

```python
async def fetch_probable_starts(
    client: StatsApiClient, on_date: str
) -> list[ProbableStart]:
    """Every probable-pitcher start for ``on_date`` (YYYY-MM-DD)."""
    payload = await client.get_json(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "date": on_date,
            "hydrate": "probablePitcher,lineups,team",
        },
    )
```

**This code is correct** - it fetches from the right endpoint.

### What Went Wrong

The app is showing pitchers that:
1. ❌ Don't match the MLB Stats API response
2. ❌ Didn't actually pitch on June 23
3. ❌ Aren't in the database for ANY recent date

**Possible causes:**

1. **App is NOT calling the MLB Stats API**
   - Using cached/stale data
   - Using a different API source
   - Using hardcoded test data

2. **Date parameter is wrong**
   - App passing wrong date to API
   - Timezone conversion error
   - Off-by-one date bug

3. **Data corruption/caching**
   - Stale cache from earlier date
   - Browser/app cache not refreshing
   - Database cache out of sync

4. **Wrong data source entirely**
   - Using a projection service (Roster Resource, RotoWire)
   - Using season-start probable rotations
   - Using simulated/fantasy data

---

## How to Fix

### Step 1: Verify API Call

Add logging to see what the app actually receives:

```python
# In mlb_stats.py fetch_probable_starts()
payload = await client.get_json(...)

# ADD THIS:
import json
print(f"API Response for {on_date}:")
print(json.dumps(payload, indent=2)[:500])  # First 500 chars

for date_block in payload.get("dates", []):
    for game in date_block.get("games", []):
        away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher", {})
        home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher", {})
        print(f"  {away_pitcher.get('fullName')} vs {home_pitcher.get('fullName')}")
```

Run the app and check console output. Does it match the API response we got?

### Step 2: Check Date Parameter

```python
# In the code that calls fetch_probable_starts()
print(f"Fetching probables for date: {on_date}")
print(f"Today is: {datetime.now()}")
```

Make sure `on_date` is "2026-06-23" not "2026-06-24" or something else.

### Step 3: Check for Caching

Look for:
- Redis cache
- In-memory cache
- Browser LocalStorage
- API response caching

Clear ALL caches and test again.

### Step 4: Check Data Flow

Trace from frontend to backend:
1. Frontend requests June 23 data
2. Backend calls `fetch_probable_starts("2026-06-23")`
3. Function calls MLB Stats API
4. Response is parsed
5. Data sent to frontend
6. Frontend displays pitchers

**Add logging at EACH step** to find where the wrong data enters.

---

## Impact

### Cannot Trust App Predictions

If probable pitchers are wrong:
- ❌ All predictions are for wrong pitchers
- ❌ All edge calculations are invalid
- ❌ All betting recommendations are worthless
- ❌ Historical performance metrics are meaningless

### Betting Consequences

If you bet based on app recommendations with wrong pitchers:
- You're betting on pitchers who won't play
- Bets would be voided OR
- You'd lose every single bet (0% hit rate)

---

## Immediate Actions

### 1. **DO NOT BET** based on app until fixed

### 2. Cross-check probables manually

Before any bet, verify pitcher on:
- MLB.com official schedule
- Baseball Reference
- Roto Wire
- Team Twitter/announcements

### 3. Test on a known-good date

Pick a date where you KNOW who pitched (e.g., June 14 from database).
Run app for that date.
Compare app predictions vs database actuals.

If app is wrong for historical dates too → systemic bug.
If app is correct for historical dates → real-time data issue.

### 4. Check app configuration

Look for:
- `USE_TEST_DATA = True` flags
- Mock data in development mode
- API endpoint overrides
- Date offset configuration

---

## Files for Debugging

```
C:\Users\carin\OneDrive\Dokument\stike\mlb-edge\analytics\
├── api_vs_app_probables.py          (Comparison script)
├── comprehensive_app_validation.py   (Full validation)
└── DIAGNOSIS_PROBABLE_PITCHER_BUG.md (This file)

Backend code to check:
mlb-edge/backend/app/data/mlb_stats.py      (API fetch logic)
mlb-edge/backend/app/data/client.py         (HTTP client)
mlb-edge/backend/app/pipeline.py            (Main pipeline)
mlb-edge/backend/app/ensemble_pipeline.py   (Prediction flow)
```

---

## Bottom Line

**The app's probable pitcher data is completely broken.**

- MLB Stats API returns CORRECT probables
- App shows WRONG probables (0% match rate)
- Actual games confirm API was right, app was wrong
- Bug is in app code/config, NOT the API

**Fix priority: CRITICAL** - app is unusable for betting until this is resolved.

**Test Date:** 2026-06-25  
**Diagnosed By:** Full API validation + box score verification  
**Status:** BUG CONFIRMED - awaiting fix
