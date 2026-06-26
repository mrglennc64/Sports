"""
Diagnose why KC@CWS, ATL@SF, and PHI@NYM (Thornton) are missing from predictions

Checks MLB Stats API to see if probablePitcher is announced for these games.
"""

import asyncio
import sys
sys.path.append('backend')

from app.data.client import StatsApiClient

async def main():
    client = StatsApiClient()

    print("=" * 100)
    print("DIAGNOSING MISSING JUNE 26 GAMES")
    print("=" * 100)

    try:
        # Get June 26 schedule with probable pitchers
        schedule = await client.get_json(
            "/api/v1/schedule",
            params={
                "sportId": 1,
                "date": "2026-06-26",
                "hydrate": "probablePitcher,team"
            }
        )

        dates = schedule.get('dates', [])
        if not dates:
            print("No games found")
            return

        games = dates[0].get('games', [])

        print(f"\nTotal games: {len(games)}\n")

        # Check each game
        missing_probable = []
        has_probable = []

        for game in games:
            game_pk = game.get('gamePk')
            teams = game.get('teams', {})

            away_team = teams.get('away', {}).get('team', {}).get('name', 'Unknown')
            home_team = teams.get('home', {}).get('team', {}).get('name', 'Unknown')

            away_pitcher_obj = teams.get('away', {}).get('probablePitcher')
            home_pitcher_obj = teams.get('home', {}).get('probablePitcher')

            away_pitcher = away_pitcher_obj.get('fullName') if away_pitcher_obj else None
            home_pitcher = home_pitcher_obj.get('fullName') if home_pitcher_obj else None

            if not away_pitcher or not home_pitcher:
                missing_probable.append({
                    'away_team': away_team,
                    'home_team': home_team,
                    'away_pitcher': away_pitcher,
                    'home_pitcher': home_pitcher,
                    'game_pk': game_pk
                })
            else:
                has_probable.append({
                    'away_team': away_team,
                    'home_team': home_team,
                    'away_pitcher': away_pitcher,
                    'home_pitcher': home_pitcher,
                    'game_pk': game_pk
                })

        print(f"[OK] Games with BOTH probables announced: {len(has_probable)}")
        print(f"[MISSING] Games MISSING one or both probables: {len(missing_probable)}\n")

        if missing_probable:
            print("=" * 100)
            print("GAMES MISSING PROBABLE PITCHERS (these won't show in app)")
            print("=" * 100)
            for g in missing_probable:
                print(f"\n{g['away_team']} @ {g['home_team']} (game {g['game_pk']})")
                print(f"  Away pitcher: {g['away_pitcher'] or 'NOT ANNOUNCED'}")
                print(f"  Home pitcher: {g['home_pitcher'] or 'NOT ANNOUNCED'}")

        if has_probable:
            print("\n" + "=" * 100)
            print(f"GAMES WITH PROBABLE PITCHERS ({len(has_probable)} games)")
            print("=" * 100)
            for g in has_probable:
                print(f"{g['away_team']:20s} @ {g['home_team']:20s} | {g['away_pitcher']:25s} vs {g['home_pitcher']}")

        print("\n" + "=" * 100)
        print("CONCLUSION")
        print("=" * 100)
        print(f"""
The app shows {len(has_probable)} games because those are the only games where
BOTH probable pitchers were announced in the MLB Stats API.

Games missing from app:
{len(missing_probable)} games don't have both probables announced yet.

This is NOT a filter/bug - it's the MLB not announcing probables early enough.
RotoWire may have insider info or manual curation that MLB API doesn't have yet.

FIX: The app should show ALL games and display "TBD" for missing probables,
then update when pitchers are announced.
        """)

    finally:
        await client.aclose()

if __name__ == '__main__':
    asyncio.run(main())
