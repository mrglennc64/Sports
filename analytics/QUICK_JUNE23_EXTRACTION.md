# Quick Guide: Extract June 23 Results from MLB.com Screenshot

## What You Need to Do

Look at your MLB.com screenshot and find each pitcher from the app predictions. In each game box, you'll see:

```
Pitcher Name
IP: X.X   K: X   ERA: X.XX
```

We need the **K** (strikeout) value.

## Pitchers to Find (from App)

### Flagged Bets (9 - these are what matters for betting performance)

1. **Zac Gallen** vs Cardinals (UNDER 3.5, exp 2.35)
2. **Bubba Chandler** vs Mariners (UNDER 4.5, exp 4.11)
3. **Michael McGreevy** vs Diamondbacks (UNDER 2.5, exp 2.45)
4. **Matthew Boyd** vs Mets (OVER 4.5, exp 5.20)
5. **Cam Schlitter** vs Red Sox (OVER 6.5, exp 6.80)
6. **Christopher Sánchez** vs Nationals (OVER 6.5, exp 6.58)
7. **Cade Cavalli** vs Phillies (UNDER 4.5, exp 5.01)
8. **Troy Melton** vs Astros (UNDER 4.5, exp 3.59)
9. **Jeffrey Springs** vs Giants (UNDER 4.5, exp 4.42)

### Unflagged (6 - for prediction accuracy only)

10. **Kevin Gausman** vs Rangers (OVER 6.5, exp 6.05)
11. **MacKenzie Gore** vs Blue Jays (UNDER 4.5, exp 5.26)
12. **Freddy Peralta** vs Cubs (UNDER 5.5, exp 4.54)
13. **Tatuya Imai** vs Tigers (UNDER 5.5, exp 5.06)
14. **Connelly Early** vs Yankees (OVER 5.5, exp 6.13)
15. **Landen Roupp** vs Athletics (UNDER 6.5, exp 5.83)

## Quick Method

1. Open `extract_june23_from_screenshot.py`
2. Find the `actual_results = {}` section (around line 40)
3. For each pitcher you find in the screenshot, add a line:
   ```python
   "Pitcher Name": actual_strikeouts,
   ```
4. Run the script:
   ```bash
   cd mlb-edge/analytics
   python extract_june23_from_screenshot.py
   ```

## Example

If you see in a game box:
```
J. Springs
IP: 6.0   K: 5   ERA: 3.00
```

Add to the script:
```python
actual_results = {
    "Jeffrey Springs": 5,
    # ... continue for all pitchers
}
```

## What the Output Will Show

1. **Betting Hit Rate** - Did flagged bets win? (need 52.4%+)
2. **Prediction MAE** - How accurate were forecasts? (want <1.8)
3. **Selection Quality** - Were flagged bets more predictable?
4. **vs Baseline** - Better or worse than 1.672 test average?

## Can't Find a Pitcher?

- Check both teams in each game box (home and away pitchers)
- Pitcher might not have started (weather/injury)
- Game might have been postponed
- Note which ones are missing

## Minimum to Test Betting Performance

At minimum, get the **9 flagged bets** (#1-9 above). Those are what determines if the app's edge-finding logic worked.

The other 6 are nice to have for full prediction accuracy testing.
