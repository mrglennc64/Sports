"""
Test that backend now shows ALL 15 June 26 games including TBD probables
"""

import sys
sys.path.append('backend')
import asyncio
import os

# Mock odds API key to avoid requiring real key for testing
os.environ['ODDS_API_KEY_THEODDSAPI'] = 'test_key_not_used'

from app.ensemble_pipeline import build_slate_ensemble
from app.data.odds import TheOddsApiProvider

# Mock the odds provider to avoid API calls
class MockOddsProvider:
    def collect_props_strikeouts(self):
        return []  # No odds for testing

# Patch the provider
import app.ensemble_pipeline
original_get_provider = app.ensemble_pipeline.get_provider

def mock_get_provider(*args, **kwargs):
    return MockOddsProvider()

app.ensemble_pipeline.get_provider = mock_get_provider

async def test():
    print("=" * 100)
    print("TESTING BACKEND FIX - SHOULD SHOW ALL 15 GAMES")
    print("=" * 100)

    try:
        result = await build_slate_ensemble("2026-06-26")

        all_rows = result.get("rows", [])

        print(f"\nTotal games/pitchers returned: {len(all_rows)}")

        # Count by status
        status_counts = {}
        for row in all_rows:
            status = row.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        print(f"\nBreakdown by status:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")

        # Show TBD games
        tbd_games = [r for r in all_rows if r.get("status") == "probable_not_announced"]
        if tbd_games:
            print(f"\n{len(tbd_games)} games with TBD probables:")
            for g in tbd_games:
                print(f"  {g.get('pitcher', 'Unknown')} vs {g.get('opponent', 'Unknown')} at {g.get('venue', 'Unknown')}")

        # Show games with predictions
        predicted_games = [r for r in all_rows if r.get("status") in ["ok", "no_market"]]
        print(f"\n{len(predicted_games)} games with predictions:")
        for g in predicted_games[:5]:  # First 5
            print(f"  {g.get('pitcher', 'Unknown'):25s} vs {g.get('opponent', 'Unknown'):25s} | Pred: {g.get('expected_ks', 0):.2f} K")

        print(f"\n{'='*100}")
        print("RESULT:")
        print(f"{'='*100}")

        expected_total = 30  # 15 games × 2 pitchers = 30 starts
        if len(all_rows) == expected_total:
            print(f"SUCCESS: All 30 starts (15 games) returned")
        else:
            print(f"WARNING: Expected 30 starts, got {len(all_rows)}")

        if tbd_games:
            print(f"SUCCESS: {len(tbd_games)} TBD games shown (not hidden)")
        else:
            print(f"INFO: All probables announced (no TBD games)")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
