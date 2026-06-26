"""
Fetch live/final results from MLB Stats API for June 26, 2026

Gets actual strikeout totals to validate predictions.
"""

import asyncio
import sys
sys.path.append('backend')

from app.data.client import StatsApiClient
import pandas as pd

async def fetch_june26_results():
    client = StatsApiClient()

    target_date = '2026-06-26'

    print("=" * 100)
    print(f"FETCHING MLB RESULTS FOR {target_date}")
    print("=" * 100)

    try:
        # Get schedule with game details
        schedule = await client.get_json(
            "/api/v1/schedule",
            params={
                "sportId": 1,
                "date": target_date,
                "hydrate": "linescore,decisions,probablePitcher"
            }
        )

        games = []
        dates = schedule.get('dates', [])

        if not dates:
            print(f"No games found for {target_date}")
            return []

        for date_obj in dates:
            for game in date_obj.get('games', []):
                game_pk = game.get('gamePk')
                status = game.get('status', {}).get('detailedState', 'Unknown')

                # Get teams
                away_team = game.get('teams', {}).get('away', {}).get('team', {}).get('name', 'Unknown')
                home_team = game.get('teams', {}).get('home', {}).get('team', {}).get('name', 'Unknown')

                # Get probable/winning pitchers
                away_pitcher = game.get('teams', {}).get('away', {}).get('probablePitcher', {}).get('fullName', 'TBD')
                home_pitcher = game.get('teams', {}).get('home', {}).get('probablePitcher', {}).get('fullName', 'TBD')

                # Get decisions (for finished games)
                decisions = game.get('decisions', {})
                winning_pitcher = decisions.get('winner', {}).get('fullName')
                losing_pitcher = decisions.get('loser', {}).get('fullName')

                # Get linescore for strikeouts
                linescore = game.get('linescore', {})
                away_strikeouts = linescore.get('teams', {}).get('away', {}).get('strikeOuts')
                home_strikeouts = linescore.get('teams', {}).get('home', {}).get('strikeOuts')

                games.append({
                    'game_pk': game_pk,
                    'status': status,
                    'away_team': away_team,
                    'home_team': home_team,
                    'away_pitcher': away_pitcher,
                    'home_pitcher': home_pitcher,
                    'away_strikeouts': away_strikeouts,
                    'home_strikeouts': home_strikeouts,
                    'winning_pitcher': winning_pitcher,
                    'losing_pitcher': losing_pitcher
                })

        return games

    finally:
        await client.aclose()

async def get_pitcher_stats_from_game(game_pk: int):
    """Get detailed pitcher stats from a specific game."""
    client = StatsApiClient()

    try:
        # Get boxscore
        boxscore = await client.get_json(
            f"/api/v1/game/{game_pk}/boxscore",
            params={}
        )

        pitcher_stats = []

        # Parse away pitchers
        away_pitchers = boxscore.get('teams', {}).get('away', {}).get('pitchers', [])
        away_pitcher_details = boxscore.get('teams', {}).get('away', {}).get('players', {})

        for pitcher_id in away_pitchers:
            player_key = f'ID{pitcher_id}'
            player = away_pitcher_details.get(player_key, {})
            name = player.get('person', {}).get('fullName', 'Unknown')
            stats = player.get('stats', {}).get('pitching', {})

            pitcher_stats.append({
                'pitcher_id': pitcher_id,
                'name': name,
                'team': 'away',
                'strikeouts': stats.get('strikeOuts', 0),
                'batters_faced': stats.get('battersFaced', 0),
                'innings': stats.get('inningsPitched', '0.0')
            })

        # Parse home pitchers
        home_pitchers = boxscore.get('teams', {}).get('home', {}).get('pitchers', [])
        home_pitcher_details = boxscore.get('teams', {}).get('home', {}).get('players', {})

        for pitcher_id in home_pitchers:
            player_key = f'ID{pitcher_id}'
            player = home_pitcher_details.get(player_key, {})
            name = player.get('person', {}).get('fullName', 'Unknown')
            stats = player.get('stats', {}).get('pitching', {})

            pitcher_stats.append({
                'pitcher_id': pitcher_id,
                'name': name,
                'team': 'home',
                'strikeouts': stats.get('strikeOuts', 0),
                'batters_faced': stats.get('battersFaced', 0),
                'innings': stats.get('inningsPitched', '0.0')
            })

        return pitcher_stats

    finally:
        await client.aclose()

async def main():
    games = await fetch_june26_results()

    if not games:
        print("No games found or API returned no data")
        return

    df = pd.DataFrame(games)

    print(f"\n[1] Found {len(games)} games on 2026-06-26\n")
    print(df.to_string(index=False))

    # Separate by status
    final_games = df[df['status'].str.contains('Final', case=False, na=False)]
    in_progress = df[df['status'].str.contains('Progress|Live', case=False, na=False)]
    scheduled = df[~df['status'].str.contains('Final|Progress|Live', case=False, na=False)]

    print(f"\n[2] GAME STATUS BREAKDOWN:")
    print(f"  Final: {len(final_games)}")
    print(f"  In Progress: {len(in_progress)}")
    print(f"  Scheduled/Postponed: {len(scheduled)}")

    # Get detailed pitcher stats for completed games
    if len(final_games) > 0:
        print(f"\n[3] DETAILED PITCHER STATS FROM COMPLETED GAMES:")
        print("=" * 100)

        all_pitcher_stats = []
        for game_pk in final_games['game_pk'].head(5):  # Limit to first 5 to avoid rate limiting
            print(f"\nFetching game {game_pk}...")
            try:
                stats = await get_pitcher_stats_from_game(game_pk)
                all_pitcher_stats.extend(stats)
            except Exception as e:
                print(f"  Error: {e}")

        if all_pitcher_stats:
            pitcher_df = pd.DataFrame(all_pitcher_stats)
            # Only starters (typically 3+ IP or 10+ batters faced)
            starters = pitcher_df[pitcher_df['batters_faced'] >= 10]
            starters = starters.sort_values('strikeouts', ascending=False)

            print("\nStarting Pitchers:")
            print(starters.to_string(index=False))

            # Save to CSV for validation
            starters.to_csv('analytics/june26_actual_strikeouts.csv', index=False)
            print(f"\nSaved to analytics/june26_actual_strikeouts.csv")

    # Save schedule
    df.to_csv('analytics/june26_games_schedule.csv', index=False)
    print(f"\nSaved full schedule to analytics/june26_games_schedule.csv")

if __name__ == '__main__':
    asyncio.run(main())
