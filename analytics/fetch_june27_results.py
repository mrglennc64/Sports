"""Fetch June 27, 2026 strikeout results and compare vs predictions"""

import sys
sys.path.append('../backend')
import asyncio
import csv
from app.data.client import StatsApiClient
from datetime import datetime

# Hardcoded predictions from the featured plays
predictions = {
    'Reid Detmers': {'line': 7.5, 'side': 'U', 'expected_ks': 7.5},
    'Logan Gilbert': {'line': 6.5, 'side': 'U', 'expected_ks': 6.5},
    'Christian Scott': {'line': 4.5, 'side': 'O', 'expected_ks': 4.5},
    'Bryce Elder': {'line': 4.5, 'side': 'O', 'expected_ks': 4.5},
}

async def fetch_june27_results():
    client = StatsApiClient()
    
    try:
        # Get games for June 27
        schedule = await client.get_json(
            '/api/v1/schedule',
            params={'sportId': 1, 'date': '2026-06-27'}
        )
        
        results = []
        
        for date_block in schedule.get('dates', []):
            games = date_block.get('games', [])
            print(f"Found {len(games)} games for 2026-06-27\n")
            
            for game in games:
                game_id = game.get('gamePk')
                teams = game.get('teams', {})
                away = teams.get('away', {}).get('team', {}).get('abbreviation', '???')
                home = teams.get('home', {}).get('team', {}).get('abbreviation', '???')
                
                away_pitcher = teams.get('away', {}).get('probablePitcher', {}).get('fullName', 'TBD')
                home_pitcher = teams.get('home', {}).get('probablePitcher', {}).get('fullName', 'TBD')
                
                print(f"Game {game_id}: {away} @ {home}")
                print(f"  {away} pitcher: {away_pitcher}")
                print(f"  {home} pitcher: {home_pitcher}\n")
                
                # Fetch boxscore for strikeout details
                try:
                    boxscore = await client.get_json(f'/api/v1/game/{game_id}/boxscore')
                    
                    for team_key in ['away', 'home']:
                        team_data = boxscore.get('teams', {}).get(team_key, {})
                        pitcher_name = away_pitcher if team_key == 'away' else home_pitcher
                        
                        players = team_data.get('players', [])
                        for player in players:
                            player_id = list(player.keys())[0] if player else None
                            if not player_id:
                                continue
                            
                            player_info = player.get(player_id, {})
                            person = player_info.get('person', {})
                            person_name = person.get('fullName')
                            
                            if person_name == pitcher_name:
                                stats = player_info.get('stats', {})
                                pitching = stats.get('pitching', {})
                                strikeouts = pitching.get('strikeOuts', 0)
                                
                                result_row = {
                                    'date': '2026-06-27',
                                    'pitcher': pitcher_name,
                                    'matchup': f"{away} @ {home}",
                                    'actual_ks': strikeouts,
                                    'predicted_ks': None,
                                    'line': None,
                                    'side': None,
                                    'direction_correct': None
                                }
                                
                                # Check if this pitcher has a prediction
                                if pitcher_name in predictions:
                                    pred = predictions[pitcher_name]
                                    result_row['predicted_ks'] = pred['expected_ks']
                                    result_row['line'] = pred['line']
                                    result_row['side'] = pred['side']
                                    
                                    # Calculate if direction is correct
                                    if pred['side'] == 'O':
                                        direction_correct = strikeouts > pred['line']
                                    else:  # 'U'
                                        direction_correct = strikeouts < pred['line']
                                    
                                    result_row['direction_correct'] = direction_correct
                                
                                results.append(result_row)
                                print(f"    Strikeouts: {strikeouts}")
                                if pitcher_name in predictions:
                                    print(f"    Prediction: {predictions[pitcher_name]['side']}{predictions[pitcher_name]['line']} (Expected: {predictions[pitcher_name]['expected_ks']} KS)")
                                    print(f"    Direction correct: {direction_correct}\n")
                
                except Exception as e:
                    print(f"  Error fetching boxscore for game {game_id}: {e}\n")
        
        return results
        
    finally:
        await client.aclose()


def calculate_stats(results):
    """Calculate MAE, bias, and hit rate"""
    predictions_with_data = [r for r in results if r['predicted_ks'] is not None]
    
    if not predictions_with_data:
        return None
    
    mae = sum(abs(r['actual_ks'] - r['predicted_ks']) for r in predictions_with_data) / len(predictions_with_data)
    bias = sum(r['predicted_ks'] - r['actual_ks'] for r in predictions_with_data) / len(predictions_with_data)
    hit_rate = sum(r['direction_correct'] for r in predictions_with_data) / len(predictions_with_data)
    
    return {
        'MAE': mae,
        'bias': bias,
        'hit_rate': hit_rate,
        'n': len(predictions_with_data)
    }


async def main():
    results = await fetch_june27_results()
    stats = calculate_stats(results)
    
    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    if stats:
        print(f"Predictions with results: {stats['n']}")
        print(f"MAE (Mean Absolute Error): {stats['MAE']:.3f}")
        print(f"Bias (Mean Error): {stats['bias']:.3f}")
        print(f"Hit Rate (Direction Correct): {stats['hit_rate']:.1%}\n")
    
    # Output as CSV
    print("\nCSV OUTPUT:")
    print("="*80)
    writer = csv.DictWriter(sys.stdout, fieldnames=results[0].keys() if results else [])
    writer.writeheader()
    for row in results:
        writer.writerow(row)


if __name__ == '__main__':
    asyncio.run(main())
