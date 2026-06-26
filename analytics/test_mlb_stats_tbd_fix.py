"""Test that fetch_probable_starts now returns ALL games including TBD"""

import sys
sys.path.append('backend')
import asyncio
from app.data.mlb_stats import fetch_probable_starts
from app.data.client import StatsApiClient

async def test():
    client = StatsApiClient()

    print("=" * 100)
    print("TESTING fetch_probable_starts FIX - SHOULD SHOW ALL GAMES INCLUDING TBD")
    print("=" * 100)

    try:
        starts = await fetch_probable_starts(client, "2026-06-26")

        print(f"\nTotal starts returned: {len(starts)}")
        print(f"Expected: 30 starts (15 games × 2 pitchers)\n")

        # Group by status
        with_prob = [s for s in starts if s.pitcher_id and s.pitcher_name != "TBD"]
        tbd = [s for s in starts if not s.pitcher_id or s.pitcher_name == "TBD"]

        print(f"Starts with probable announced: {len(with_prob)}")
        print(f"Starts showing TBD: {len(tbd)}\n")

        if tbd:
            print("TBD starters:")
            for s in tbd:
                print(f"  {s.pitcher_name:25s} vs {s.opponent_team_name:25s}")

        print(f"\nFirst 10 starts with probables:")
        for s in with_prob[:10]:
            print(f"  {s.pitcher_name:25s} vs {s.opponent_team_name:25s}")

        print(f"\n{'='*100}")
        print("RESULT:")
        print(f"{'='*100}")

        if len(starts) == 30:
            print("SUCCESS: All 30 starts (15 games) returned")
        else:
            print(f"ISSUE: Expected 30 starts, got {len(starts)}")

        if tbd:
            print(f"SUCCESS: {len(tbd)} TBD starts included (not filtered out)")
        else:
            print("INFO: All probables announced (no TBD starts)")

    finally:
        await client.aclose()

asyncio.run(test())
