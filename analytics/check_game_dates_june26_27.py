"""Check which games MLB API returns for June 26 vs June 27"""

import sys
sys.path.append('backend')
import asyncio
from app.data.client import StatsApiClient

async def check():
    client = StatsApiClient()

    try:
        for check_date in ['2026-06-26', '2026-06-27']:
            print(f"Requesting: {check_date}")
            print("=" * 80)

            schedule = await client.get_json(
                '/api/v1/schedule',
                params={'sportId': 1, 'date': check_date}
            )

            for date_block in schedule.get('dates', []):
                actual_date = date_block.get('date')
                games = date_block.get('games', [])

                print(f"  Date block returned: {actual_date}")
                print(f"  Games in this block: {len(games)}\n")

                for game in games:
                    teams = game.get('teams', {})
                    away = teams.get('away', {}).get('team', {}).get('abbreviation', '???')
                    home = teams.get('home', {}).get('team', {}).get('abbreviation', '???')

                    away_prob = teams.get('away', {}).get('probablePitcher', {}).get('fullName', 'TBD')
                    home_prob = teams.get('home', {}).get('probablePitcher', {}).get('fullName', 'TBD')

                    print(f"    {away} @ {home}: {away_prob} vs {home_prob}")

            print()

    finally:
        await client.aclose()

asyncio.run(check())
