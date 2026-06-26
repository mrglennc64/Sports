"""
Ingest June 26, 2026 play-by-play data into DuckDB

Updates the database with today's games once they complete.
Uses MLB Stats API to fetch play-by-play events.
"""

import asyncio
import sys
sys.path.append('backend')

from app.data.client import StatsApiClient
import duckdb
import pandas as pd
from datetime import datetime

async def fetch_game_play_by_play(game_pk: int, client: StatsApiClient):
    """Fetch all play-by-play events for a game."""
    try:
        # Get play-by-play data
        feed = await client.get_json(
            f"/api/v1.1/game/{game_pk}/feed/live",
            params={}
        )

        game_data = feed.get('gameData', {})
        live_data = feed.get('liveData', {})

        game_date = game_data.get('datetime', {}).get('officialDate')
        game_type = game_data.get('game', {}).get('type')
        season = game_data.get('game', {}).get('season')

        plays = live_data.get('plays', {}).get('allPlays', [])

        events = []
        for play in plays:
            result = play.get('result', {})
            about = play.get('about', {})
            matchup = play.get('matchup', {})
            count = play.get('count', {})

            # Get pitcher and batter
            pitcher_id = matchup.get('pitcher', {}).get('id')
            batter_id = matchup.get('batter', {}).get('id')

            # Get event details
            event_type = result.get('event')
            description = result.get('description')

            # Play index
            at_bat_index = about.get('atBatIndex')
            inning = about.get('inning')

            # Count
            balls = count.get('balls')
            strikes = count.get('strikes')

            # Batted ball data (if available)
            play_events = play.get('playEvents', [])
            pitch_data = None
            for pe in play_events:
                if pe.get('isPitch') and pe.get('details', {}).get('type'):
                    pitch_data = pe

            pitch_type = None
            launch_speed = None
            launch_angle = None
            bb_type = None

            if pitch_data:
                pitch_type = pitch_data.get('details', {}).get('type', {}).get('code')

            # Hit data
            hit_data = result.get('hitData', {})
            if hit_data:
                launch_speed = hit_data.get('launchSpeed')
                launch_angle = hit_data.get('launchAngle')
                bb_type = hit_data.get('trajectory')

            # Stands/throws
            stand = matchup.get('batSide', {}).get('code')
            p_throws = matchup.get('pitchHand', {}).get('code')

            # Teams
            teams = game_data.get('teams', {})
            home_team = teams.get('home', {}).get('name')
            away_team = teams.get('away', {}).get('name')

            # Pitcher name
            pitcher_name = matchup.get('pitcher', {}).get('fullName')

            events.append({
                'season': season,
                'game_pk': game_pk,
                'game_date': game_date,
                'game_type': game_type,
                'at_bat_number': at_bat_index,
                'inning': inning,
                'batter': batter_id,
                'pitcher': pitcher_id,
                'stand': stand,
                'p_throws': p_throws,
                'events': event_type,
                'description': description,
                'bb_type': bb_type,
                'pitch_type': pitch_type,
                'balls': balls,
                'strikes': strikes,
                'pitches_in_pa': len([p for p in play_events if p.get('isPitch')]),
                'launch_speed': launch_speed,
                'launch_angle': launch_angle,
                'home_team': home_team,
                'away_team': away_team,
                'player_name': pitcher_name
            })

        return events

    except Exception as e:
        print(f"Error fetching game {game_pk}: {e}")
        return []

async def ingest_date(target_date: str):
    """Ingest all games from a specific date."""
    client = StatsApiClient()

    print("=" * 100)
    print(f"INGESTING PLAY-BY-PLAY DATA FOR {target_date}")
    print("=" * 100)

    try:
        # Get schedule
        schedule = await client.get_json(
            "/api/v1/schedule",
            params={
                "sportId": 1,
                "date": target_date,
                "hydrate": "linescore"
            }
        )

        dates = schedule.get('dates', [])
        if not dates:
            print(f"No games found for {target_date}")
            return

        games = dates[0].get('games', [])
        game_pks = [g['gamePk'] for g in games]

        print(f"\nFound {len(game_pks)} games")

        # Filter to final games only
        final_games = [
            g['gamePk'] for g in games
            if 'Final' in g.get('status', {}).get('detailedState', '')
        ]

        print(f"  Final games: {len(final_games)}")
        print(f"  In progress/scheduled: {len(game_pks) - len(final_games)}")

        if len(final_games) == 0:
            print("\nNo completed games to ingest yet. Games may still be in progress or scheduled.")
            return

        # Fetch play-by-play for each final game
        all_events = []
        for i, game_pk in enumerate(final_games, 1):
            print(f"\n[{i}/{len(final_games)}] Fetching game {game_pk}...")
            events = await fetch_game_play_by_play(game_pk, client)
            all_events.extend(events)
            print(f"  Got {len(events)} plate appearances")

            # Rate limit
            await asyncio.sleep(0.5)

        if not all_events:
            print("\nNo events fetched")
            return

        # Convert to DataFrame
        df = pd.DataFrame(all_events)
        print(f"\n[3] INGESTION SUMMARY:")
        print(f"  Total PAs: {len(df)}")
        print(f"  Games: {df['game_pk'].nunique()}")
        print(f"  Pitchers: {df['pitcher'].nunique()}")
        print(f"  Batters: {df['batter'].nunique()}")

        # Insert into DuckDB
        con = duckdb.connect('data/baseball.duckdb')

        # Check if data already exists
        existing = con.execute(f"""
            SELECT COUNT(*) as cnt
            FROM pa_events
            WHERE game_date = '{target_date}'
        """).fetchone()[0]

        if existing > 0:
            print(f"\nWARNING: Found {existing} existing PAs for {target_date}")
            print("Deleting existing data before insert...")
            con.execute(f"DELETE FROM pa_events WHERE game_date = '{target_date}'")

        # Insert new data
        con.execute("INSERT INTO pa_events SELECT * FROM df")

        # Verify
        new_count = con.execute(f"""
            SELECT COUNT(*) as cnt
            FROM pa_events
            WHERE game_date = '{target_date}'
        """).fetchone()[0]

        print(f"\n[4] DATABASE UPDATE:")
        print(f"  Inserted: {new_count} PAs")
        print(f"  Date: {target_date}")

        # Show sample
        sample = con.execute(f"""
            SELECT pitcher, COUNT(*) as pa, SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as k
            FROM pa_events
            WHERE game_date = '{target_date}'
            GROUP BY pitcher
            HAVING pa >= 10
            ORDER BY k DESC
            LIMIT 10
        """).fetchdf()

        print(f"\n[5] TOP STRIKEOUT PERFORMANCES:")
        print(sample.to_string(index=False))

        con.close()

        print(f"\n{'='*100}")
        print("INGESTION COMPLETE")
        print(f"{'='*100}")

    finally:
        await client.aclose()

if __name__ == '__main__':
    import sys
    target_date = sys.argv[1] if len(sys.argv) > 1 else '2026-06-26'
    asyncio.run(ingest_date(target_date))
