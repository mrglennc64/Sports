"""
Simple ingestion script for June 26, 2026 data
Uses requests library instead of backend modules.
"""

import requests
import duckdb
import pandas as pd
import time

def fetch_schedule(date: str):
    """Get games for a date."""
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date": date,
        "hydrate": "linescore"
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def fetch_game_feed(game_pk: int):
    """Get play-by-play for a game."""
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def parse_game_events(game_pk: int, feed: dict):
    """Parse play-by-play events from game feed."""
    game_data = feed.get('gameData', {})
    live_data = feed.get('liveData', {})

    game_date = game_data.get('datetime', {}).get('officialDate')
    game_type = game_data.get('game', {}).get('type')
    season = game_data.get('game', {}).get('season')

    teams = game_data.get('teams', {})
    home_team = teams.get('home', {}).get('name')
    away_team = teams.get('away', {}).get('name')

    plays = live_data.get('plays', {}).get('allPlays', [])

    events = []
    for play in plays:
        result = play.get('result', {})
        about = play.get('about', {})
        matchup = play.get('matchup', {})
        count = play.get('count', {})

        # Core data
        pitcher_id = matchup.get('pitcher', {}).get('id')
        batter_id = matchup.get('batter', {}).get('id')

        event_type = result.get('event')
        description = result.get('description')

        at_bat_index = about.get('atBatIndex')
        inning = about.get('inning')

        balls = count.get('balls', 0)
        strikes = count.get('strikes', 0)

        # Hit data
        hit_data = result.get('hitData', {})
        launch_speed = hit_data.get('launchSpeed')
        launch_angle = hit_data.get('launchAngle')
        bb_type = hit_data.get('trajectory')

        # Sides
        stand = matchup.get('batSide', {}).get('code')
        p_throws = matchup.get('pitchHand', {}).get('code')

        # Pitch data
        play_events = play.get('playEvents', [])
        pitch_type = None
        for pe in play_events:
            if pe.get('isPitch'):
                pitch_type = pe.get('details', {}).get('type', {}).get('code')
                if pitch_type:
                    break

        pitches_in_pa = len([p for p in play_events if p.get('isPitch')])

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
            'pitches_in_pa': pitches_in_pa,
            'launch_speed': launch_speed,
            'launch_angle': launch_angle,
            'home_team': home_team,
            'away_team': away_team,
            'player_name': pitcher_name
        })

    return events

def main(target_date='2026-06-26'):
    print("=" * 100)
    print(f"INGESTING {target_date} DATA")
    print("=" * 100)

    # Get schedule
    schedule = fetch_schedule(target_date)
    dates = schedule.get('dates', [])

    if not dates:
        print(f"No games found for {target_date}")
        return

    games = dates[0].get('games', [])

    # Filter final games
    final_games = [
        g for g in games
        if 'Final' in g.get('status', {}).get('detailedState', '')
    ]

    print(f"\nFound {len(games)} total games")
    print(f"  Final: {len(final_games)}")
    print(f"  Not final: {len(games) - len(final_games)}")

    if len(final_games) == 0:
        print("\nNo completed games yet. Check back after games finish!")
        return

    # Fetch each game
    all_events = []
    for i, game in enumerate(final_games, 1):
        game_pk = game['gamePk']
        away = game.get('teams', {}).get('away', {}).get('team', {}).get('name', '?')
        home = game.get('teams', {}).get('home', {}).get('team', {}).get('name', '?')

        print(f"\n[{i}/{len(final_games)}] Fetching {away} @ {home} (game {game_pk})...")

        try:
            feed = fetch_game_feed(game_pk)
            events = parse_game_events(game_pk, feed)
            all_events.extend(events)
            print(f"  Got {len(events)} PAs")
            time.sleep(0.5)  # Rate limit
        except Exception as e:
            print(f"  ERROR: {e}")

    if not all_events:
        print("\nNo events to insert")
        return

    # Convert to DataFrame
    df = pd.DataFrame(all_events)
    print(f"\n[SUMMARY]")
    print(f"  Total PAs: {len(df)}")
    print(f"  Strikeouts: {(df['events'] == 'strikeout').sum()}")

    # Insert into database
    con = duckdb.connect('data/baseball.duckdb')

    # Delete existing (if any)
    existing = con.execute(f"SELECT COUNT(*) FROM pa_events WHERE game_date = '{target_date}'").fetchone()[0]
    if existing > 0:
        print(f"\nRemoving {existing} existing PAs...")
        con.execute(f"DELETE FROM pa_events WHERE game_date = '{target_date}'")

    # Insert
    con.execute("INSERT INTO pa_events SELECT * FROM df")

    # Verify
    new_count = con.execute(f"SELECT COUNT(*) FROM pa_events WHERE game_date = '{target_date}'").fetchone()[0]
    print(f"Inserted {new_count} PAs")

    # Show pitcher stats
    pitcher_stats = con.execute(f"""
        SELECT
            pitcher,
            COUNT(*) as bf,
            SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END) as k
        FROM pa_events
        WHERE game_date = '{target_date}'
        GROUP BY pitcher
        HAVING bf >= 10
        ORDER BY k DESC
    """).fetchdf()

    print(f"\n[PITCHER STRIKEOUTS]")
    print(pitcher_stats.to_string(index=False))

    con.close()

    print(f"\n{'='*100}")
    print("DONE")
    print(f"{'='*100}")

if __name__ == '__main__':
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else '2026-06-26'
    main(date)
