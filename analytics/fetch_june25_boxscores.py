"""
Fetch June 25, 2026 final strikeout totals from MLB Stats API
"""

import requests
import pandas as pd
import time

def fetch_schedule(date):
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {"sportId": 1, "date": date, "hydrate": "linescore,decisions"}
    response = requests.get(url, params=params)
    return response.json()

def fetch_boxscore(game_pk):
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    response = requests.get(url)
    return response.json()

def extract_pitcher_strikeouts(boxscore, game_pk):
    """Extract starting pitcher strikeouts from boxscore."""
    pitchers = []

    for side in ['away', 'home']:
        team_name = boxscore.get('teams', {}).get(side, {}).get('team', {}).get('name', 'Unknown')
        pitcher_ids = boxscore.get('teams', {}).get(side, {}).get('pitchers', [])
        players = boxscore.get('teams', {}).get(side, {}).get('players', {})

        # Find starter (first pitcher who pitched)
        for pid in pitcher_ids:
            player_key = f'ID{pid}'
            player = players.get(player_key, {})
            stats = player.get('stats', {}).get('pitching', {})

            name = player.get('person', {}).get('fullName', 'Unknown')
            ip = stats.get('inningsPitched', '0.0')
            so = stats.get('strikeOuts', 0)
            bf = stats.get('battersFaced', 0)

            # Starter typically faces 10+ batters
            if bf >= 10:
                pitchers.append({
                    'game_pk': game_pk,
                    'name': name,
                    'team': team_name,
                    'ip': ip,
                    'strikeouts': so,
                    'batters_faced': bf
                })
                break  # Only take first (starter)

    return pitchers

def main():
    date = '2026-06-25'

    print("=" * 100)
    print(f"FETCHING JUNE 25, 2026 STRIKEOUT RESULTS")
    print("=" * 100)

    # Get schedule
    schedule = fetch_schedule(date)
    dates = schedule.get('dates', [])

    if not dates:
        print("No games found")
        return

    games = dates[0].get('games', [])
    final_games = [g for g in games if 'Final' in g.get('status', {}).get('detailedState', '')]

    print(f"\nFound {len(final_games)} final games on {date}")

    # Fetch boxscores
    all_pitchers = []
    for i, game in enumerate(final_games, 1):
        game_pk = game['gamePk']
        away = game.get('teams', {}).get('away', {}).get('team', {}).get('name', '?')
        home = game.get('teams', {}).get('home', {}).get('team', {}).get('name', '?')

        print(f"\n[{i}/{len(final_games)}] {away} @ {home} (game {game_pk})")

        try:
            boxscore = fetch_boxscore(game_pk)
            pitchers = extract_pitcher_strikeouts(boxscore, game_pk)
            all_pitchers.extend(pitchers)

            for p in pitchers:
                print(f"  {p['name']:30s} ({p['team']:20s}): {p['strikeouts']} K in {p['ip']} IP")

            time.sleep(0.3)  # Rate limit
        except Exception as e:
            print(f"  Error: {e}")

    # Save results
    df = pd.DataFrame(all_pitchers)
    df = df.sort_values('strikeouts', ascending=False)

    print(f"\n{'='*100}")
    print("ALL STARTING PITCHERS - SORTED BY STRIKEOUTS")
    print(f"{'='*100}\n")
    print(df.to_string(index=False))

    # Save to CSV
    df.to_csv('analytics/june25_actual_results.csv', index=False)
    print(f"\n\nSaved to analytics/june25_actual_results.csv")

if __name__ == '__main__':
    main()
