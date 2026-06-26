"""Fetch actual June 23, 2026 results from Baseball Reference or MLB Stats API.

Since the screenshot text is too small to read reliably, this attempts to
fetch the actual data programmatically.

Options:
1. MLB Stats API (free, no key needed)
2. Baseball Reference web scraping
3. Manual entry helper with team matchups
"""

import requests
from datetime import datetime

# Pitchers we need to find
PITCHERS_TO_FIND = {
    "Zac Gallen": "Cardinals",
    "Bubba Chandler": "Mariners",
    "Michael McGreevy": "Diamondbacks",
    "Matthew Boyd": "Mets",
    "Cam Schlitter": "Red Sox",
    "Christopher Sánchez": "Nationals",
    "Cade Cavalli": "Phillies",
    "Troy Melton": "Astros",
    "Jeffrey Springs": "Giants",
    "Kevin Gausman": "Rangers",
    "MacKenzie Gore": "Blue Jays",
    "Freddy Peralta": "Cubs",
    "Tatuya Imai": "Tigers",
    "Connelly Early": "Yankees",
    "Landen Roupp": "Athletics",
}


def try_mlb_stats_api():
    """Try to fetch from MLB Stats API."""
    # MLB Stats API endpoint for schedule
    date_str = "2026-06-23"
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=linescore,decisions"

    try:
        print(f"Fetching from MLB Stats API for {date_str}...")
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            games = data.get('dates', [{}])[0].get('games', [])

            print(f"\nFound {len(games)} games on {date_str}")

            results = {}
            for game in games:
                # Get pitchers from the game
                away_team = game.get('teams', {}).get('away', {}).get('team', {}).get('name', '')
                home_team = game.get('teams', {}).get('home', {}).get('team', {}).get('name', '')

                # Try to get pitcher stats from game data
                # This would need the boxscore endpoint for detailed stats
                game_pk = game.get('gamePk')
                if game_pk:
                    box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
                    box_response = requests.get(box_url, timeout=10)
                    if box_response.status_code == 200:
                        boxscore = box_response.json()
                        # Parse boxscore for pitcher stats
                        # ... (would need to parse the boxscore structure)

            return results
        else:
            print(f"API returned status {response.status_code}")
            return None

    except Exception as e:
        print(f"Error fetching from MLB Stats API: {e}")
        return None


def manual_entry_helper():
    """Interactive helper to enter results manually."""
    print("\n" + "="*80)
    print("MANUAL ENTRY HELPER")
    print("="*80)
    print("\nLook at the MLB.com screenshot or Baseball Reference for June 23, 2026")
    print("Enter the strikeout total for each pitcher (or 'skip' if not found)\n")

    results = {}
    for pitcher, opponent in PITCHERS_TO_FIND.items():
        while True:
            response = input(f"{pitcher} vs {opponent}: ").strip()
            if response.lower() == 'skip':
                print(f"  Skipping {pitcher}")
                break
            try:
                k_total = int(response)
                results[pitcher] = k_total
                print(f"  Recorded: {pitcher} = {k_total} K")
                break
            except ValueError:
                print("  Please enter a number or 'skip'")

    return results


def save_results(results):
    """Save results to extract_june23_from_screenshot.py"""
    if not results:
        print("\nNo results to save")
        return

    # Read current file
    with open('extract_june23_from_screenshot.py', 'r') as f:
        content = f.read()

    # Build the actual_results dict string
    results_str = "actual_results = {\n"
    for pitcher, k_total in results.items():
        results_str += f'    "{pitcher}": {k_total},\n'
    results_str += "}"

    # Replace the empty actual_results dict
    import re
    pattern = r'actual_results = \{[^}]*\}'
    new_content = re.sub(pattern, results_str, content, flags=re.DOTALL)

    # Write back
    with open('extract_june23_from_screenshot.py', 'w') as f:
        f.write(new_content)

    print(f"\n✓ Saved {len(results)} results to extract_june23_from_screenshot.py")
    print("\nNow run: python extract_june23_from_screenshot.py")


if __name__ == "__main__":
    print("="*80)
    print("FETCH JUNE 23, 2026 ACTUAL RESULTS")
    print("="*80)

    # Try API first
    results = try_mlb_stats_api()

    if not results:
        print("\nAPI fetch failed or incomplete. Using manual entry...")
        results = manual_entry_helper()

    if results:
        save_results(results)
        print(f"\nFound results for {len(results)} pitchers")
    else:
        print("\nNo results collected")
