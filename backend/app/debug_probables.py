"""Debug script to trace probable pitcher data flow.

Run this to see exactly what the MLB Stats API returns vs what the app uses.

Usage:
    cd mlb-edge/backend
    python -m app.debug_probables 2026-06-23
"""

import asyncio
import json
import sys
from datetime import date as date_type

from app.data.client import StatsApiClient
from app.data.mlb_stats import fetch_probable_starts


async def debug_probables(date_str: str):
    """Fetch and display probable pitchers for debugging."""

    print("="*90)
    print(f"DEBUG: Probable Pitchers for {date_str}")
    print("="*90)

    client = StatsApiClient()

    try:
        # Step 1: Raw API call
        print("\n[STEP 1] Raw MLB Stats API Response")
        print("-"*90)

        raw_response = await client.get_json(
            "/api/v1/schedule",
            params={
                "sportId": 1,
                "date": date_str,
                "hydrate": "probablePitcher,lineups,team",
            },
        )

        print(f"Total games: {raw_response.get('totalGames', 0)}")
        print(f"Total items: {raw_response.get('totalItems', 0)}")

        # Step 2: Show first game in detail
        dates = raw_response.get("dates", [])
        if dates:
            games = dates[0].get("games", [])
            if games:
                print(f"\nFirst game (sample):")
                game = games[0]
                print(json.dumps({
                    "gamePk": game.get("gamePk"),
                    "away": {
                        "team": game.get("teams", {}).get("away", {}).get("team", {}).get("name"),
                        "probablePitcher": game.get("teams", {}).get("away", {}).get("probablePitcher", {}).get("fullName"),
                    },
                    "home": {
                        "team": game.get("teams", {}).get("home", {}).get("team", {}).get("name"),
                        "probablePitcher": game.get("teams", {}).get("home", {}).get("probablePitcher", {}).get("fullName"),
                    }
                }, indent=2))

        # Step 3: Parsed probables from our function
        print("\n\n[STEP 2] Parsed via fetch_probable_starts()")
        print("-"*90)

        starts = await fetch_probable_starts(client, date_str)

        print(f"Total starts: {len(starts)}")
        print()

        for i, start in enumerate(starts, 1):
            print(f"{i:2}. {start.pitcher_name:<30} (ID:{start.pitcher_id}) "
                  f"vs {start.opponent_team_name:<25} @ {start.venue_name}")

        # Step 4: Check for specific pitchers from app screenshot
        print("\n\n[STEP 3] Check App's June 23 Predictions")
        print("-"*90)

        app_pitchers = [
            "Zac Gallen",
            "Bubba Chandler",
            "Michael McGreevy",
            "Matthew Boyd",
            "Cam Schlitter",
            "Christopher Sánchez",
            "Cade Cavalli",
            "Troy Melton",
            "Jeffrey Springs",
        ]

        found_count = 0
        for pitcher_name in app_pitchers:
            last_name = pitcher_name.split()[-1].lower()
            found = any(last_name in s.pitcher_name.lower() for s in starts)

            status = "✓ FOUND" if found else "✗ NOT FOUND"
            print(f"{status:12} {pitcher_name}")
            if found:
                found_count += 1

        print("\n" + "="*90)
        print(f"MATCH RATE: {found_count} / {len(app_pitchers)} ({found_count/len(app_pitchers)*100:.0f}%)")
        print("="*90)

        if found_count == 0:
            print("\n⚠️  CRITICAL: NONE of the app's predicted pitchers are in the API response!")
            print("   This confirms the app is NOT using the MLB Stats API correctly.")
            print()
            print("   Possible causes:")
            print("   1. App is using cached/stale data")
            print("   2. App is calling API with wrong date parameter")
            print("   3. App has a different code path (not using fetch_probable_starts)")
            print("   4. App is using test/mock data")
        elif found_count < len(app_pitchers):
            print(f"\n⚠️  PARTIAL MATCH: Only {found_count}/{len(app_pitchers)} pitchers found")
            print("   Some predicted pitchers are correct, others are wrong.")
        else:
            print("\n✓ ALL MATCHED: App probables match API perfectly!")

    finally:
        await client.aclose()


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else str(date_type.today())
    asyncio.run(debug_probables(date_str))
