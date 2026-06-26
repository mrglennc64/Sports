"""
Check June 25 probable pitchers vs actual starters

This will help explain why screenshot predictions don't match actual results.
"""

import requests
import pandas as pd

def fetch_schedule_with_probables(date):
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date": date,
        "hydrate": "probablePitcher,linescore,decisions"
    }
    response = requests.get(url, params=params)
    return response.json()

def main():
    date = '2026-06-25'

    print("=" * 100)
    print(f"JUNE 25, 2026: PROBABLE vs ACTUAL STARTERS")
    print("=" * 100)

    schedule = fetch_schedule_with_probables(date)

    games = []
    for date_obj in schedule.get('dates', []):
        for game in date_obj.get('games', []):
            game_pk = game['gamePk']
            status = game.get('status', {}).get('detailedState', 'Unknown')

            away_team = game.get('teams', {}).get('away', {}).get('team', {}).get('name', 'Unknown')
            home_team = game.get('teams', {}).get('home', {}).get('team', {}).get('name', 'Unknown')

            # PROBABLE pitchers (scheduled before game)
            away_probable = game.get('teams', {}).get('away', {}).get('probablePitcher', {}).get('fullName', 'TBD')
            home_probable = game.get('teams', {}).get('home', {}).get('probablePitcher', {}).get('fullName', 'TBD')

            # DECISIONS (actual pitchers who got W/L/SV)
            decisions = game.get('decisions', {})
            winner = decisions.get('winner', {}).get('fullName', 'N/A')
            loser = decisions.get('loser', {}).get('fullName', 'N/A')

            games.append({
                'game_pk': game_pk,
                'status': status,
                'away_team': away_team,
                'home_team': home_team,
                'away_probable': away_probable,
                'home_probable': home_probable,
                'winner': winner,
                'loser': loser
            })

    df = pd.DataFrame(games)

    print(f"\nFound {len(df)} games\n")
    print(df.to_string(index=False))

    # Save
    df.to_csv('analytics/june25_probable_vs_actual.csv', index=False)
    print(f"\nSaved to analytics/june25_probable_vs_actual.csv")

    # Now fetch boxscores to get ACTUAL starters (not just W/L pitchers)
    print("\n" + "=" * 100)
    print("FETCHING ACTUAL STARTING PITCHERS FROM BOXSCORES")
    print("=" * 100)

    actual_starters = []
    for game_pk in df['game_pk']:
        try:
            url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            response = requests.get(url)
            boxscore = response.json()

            # Get starters (pitchers who faced 10+ batters)
            for side in ['away', 'home']:
                team_name = boxscore.get('teams', {}).get(side, {}).get('team', {}).get('name', 'Unknown')
                pitchers = boxscore.get('teams', {}).get(side, {}).get('pitchers', [])
                players = boxscore.get('teams', {}).get(side, {}).get('players', {})

                for pid in pitchers:
                    player_key = f'ID{pid}'
                    player = players.get(player_key, {})
                    stats = player.get('stats', {}).get('pitching', {})

                    name = player.get('person', {}).get('fullName', 'Unknown')
                    bf = stats.get('battersFaced', 0)
                    so = stats.get('strikeOuts', 0)
                    ip = stats.get('inningsPitched', '0.0')

                    if bf >= 10:  # Starter
                        actual_starters.append({
                            'game_pk': game_pk,
                            'team': team_name,
                            'pitcher': name,
                            'batters_faced': bf,
                            'strikeouts': so,
                            'innings': ip
                        })
                        break  # Only first pitcher
        except Exception as e:
            print(f"Error fetching game {game_pk}: {e}")

    starters_df = pd.DataFrame(actual_starters)
    starters_df = starters_df.sort_values('strikeouts', ascending=False)

    print(f"\n{len(starters_df)} actual starters:\n")
    print(starters_df.to_string(index=False))

    # Save
    starters_df.to_csv('analytics/june25_actual_starters.csv', index=False)
    print(f"\nSaved to analytics/june25_actual_starters.csv")

    # Compare probables to actuals
    print("\n" + "=" * 100)
    print("ANALYSIS: Did probable pitchers match actual starters?")
    print("=" * 100)

    all_probables = set(df['away_probable'].tolist() + df['home_probable'].tolist())
    all_actuals = set(starters_df['pitcher'].tolist())

    all_probables.discard('TBD')
    all_probables.discard('N/A')

    matches = all_probables & all_actuals
    probables_only = all_probables - all_actuals
    actuals_only = all_actuals - all_probables

    print(f"\nProbable pitchers listed: {len(all_probables)}")
    print(f"Actual starters: {len(all_actuals)}")
    print(f"Matches: {len(matches)} ({100*len(matches)/len(all_probables):.1f}%)")

    if probables_only:
        print(f"\nProbable but DIDN'T start ({len(probables_only)}):")
        for p in sorted(probables_only):
            print(f"  - {p}")

    if actuals_only:
        print(f"\nActual starters NOT listed as probable ({len(actuals_only)}):")
        for p in sorted(actuals_only):
            print(f"  - {p}")

if __name__ == '__main__':
    main()
