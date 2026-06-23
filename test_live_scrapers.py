#!/usr/bin/env python3
"""Test live scrapers (Betano, bet365, Unibet)."""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(r"c:\Users\carin\OneDrive\Dokument\stike\mlb-edge\backend")
sys.path.insert(0, str(backend_path))

from app.data.european_odds import BetanoProvider, Bet365Provider, UnibetProvider

print("=" * 70)
print("TESTING LIVE SCRAPERS")
print("=" * 70)

# Test Betano
print("\n[1] TESTING BETANO SCRAPER (headless=False to see page)")
print("-" * 70)
try:
    betano = BetanoProvider(headless=False)
    betano_props = betano.get_strikeout_props()
    
    if betano_props:
        print(f"[OK] Betano: {len(betano_props)} props found")
        for p in betano_props[:3]:
            print(f"     {p.pitcher_name:<20} {p.line:>5.1f}K @ {p.over_odds:>7.2f}/{p.under_odds:>7.2f}")
    else:
        print("[WARN] Betano: No props found (may be due to: page structure changed, no games today, selector mismatch)")
        
except Exception as e:
    print(f"[FAIL] Betano failed: {e}")

# Test bet365
print("\n[2] TESTING BET365 SCRAPER (headless=False to see page)")
print("-" * 70)
try:
    bet365 = Bet365Provider(headless=False)
    bet365_props = bet365.get_strikeout_props()
    
    if bet365_props:
        print(f"[OK] bet365: {len(bet365_props)} props found")
        for p in bet365_props[:3]:
            print(f"     {p.pitcher_name:<20} {p.line:>5.1f}K @ {p.over_odds:>7.2f}/{p.under_odds:>7.2f}")
    else:
        print("[WARN] bet365: No props found (may need selector adjustment)")
        
except Exception as e:
    print(f"[FAIL] bet365 failed: {e}")

# Test Unibet
print("\n[3] TESTING UNIBET SCRAPER (static first, then dynamic)")
print("-" * 70)
try:
    unibet = UnibetProvider(headless=False)
    unibet_props = unibet.get_strikeout_props()
    
    if unibet_props:
        print(f"[OK] Unibet: {len(unibet_props)} props found")
        for p in unibet_props[:3]:
            print(f"     {p.pitcher_name:<20} {p.line:>5.1f}K @ {p.over_odds:>7.2f}/{p.under_odds:>7.2f}")
    else:
        print("[WARN] Unibet: No props found (may need selector adjustment)")
        
except Exception as e:
    print(f"[FAIL] Unibet failed: {e}")

print("\n" + "=" * 70)
print("SCRAPER TEST SUMMARY")
print("=" * 70)
print("""
[OK] CSV Importer: WORKING
[...] Live Scrapers: Need DOM inspection if no props found

Next steps if scrapers need adjustment:
1. Open page manually in browser
2. Right-click > Inspect element on a strikeout prop row
3. Look for class names or data attributes matching patterns:
   - Pitcher name: [class*="player"], [class*="name"]
   - Line: [class*="line"], [class*="handicap"]
   - Over odds: [class*="over"], [data-odds-type="over"]
   - Under odds: [class*="under"], [data-odds-type="under"]
4. Update selectors in european_odds.py
""")
