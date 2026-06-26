"""Parse MLB Stats API probables vs App predictions for June 23

Shows EXACTLY what the API returned vs what the app displayed.
"""

# From MLB Stats API for June 23, 2026 (extracted from JSON)
API_PROBABLES = {
    # Game 1: Astros @ Blue Jays
    "Houston Astros": "Peter Lambert",
    "Toronto Blue Jays": "Shane Bieber",

    # Game 2: Mariners @ Pirates
    "Seattle Mariners": "George Kirby",
    "Pittsburgh Pirates": "Mitch Keller",

    # Game 3: Royals @ Rays
    "Kansas City Royals": "Luinder Avila",
    "Tampa Bay Rays": "Shane McClanahan",

    # Game 4: Rangers @ Marlins
    "Texas Rangers": "Cal Quantrill",
    "Miami Marlins": "Sandy Alcantara",

    # Game 5: Yankees @ Tigers
    "New York Yankees": "Carlos Rodón",
    "Detroit Tigers": "Casey Mize",

    # Game 6: Phillies @ Nationals
    "Philadelphia Phillies": "Jesús Luzardo",
    "Washington Nationals": "PJ Poulin",

    # Game 7: Cubs @ Mets
    "Chicago Cubs": "Edward Cabrera",
    "New York Mets": "Kodai Senga",

    # Game 8: Brewers @ Reds
    "Milwaukee Brewers": "Brandon Sproat",
    "Cincinnati Reds": "Nick Lodolo",

    # Game 9: Dodgers @ Twins
    "Los Angeles Dodgers": "Justin Wrobleski",
    "Minnesota Twins": "Kendry Rojas",

    # Game 10: Guardians @ White Sox
    "Cleveland Guardians": "Parker Messick",
    "Chicago White Sox": "Sean Burke",

    # Game 11: D-backs @ Cardinals
    "Arizona Diamondbacks": "Eduardo Rodriguez",
    "St. Louis Cardinals": "Kyle Leahy",

    # Game 12: Red Sox @ Rockies
    "Boston Red Sox": "Sonny Gray",
    "Colorado Rockies": "Sean Sullivan",

    # Game 13: Orioles @ Angels
    "Baltimore Orioles": "Shane Baz",
    "Los Angeles Angels": "Ryan Johnson",

    # Game 14: Braves @ Padres
    "Atlanta Braves": "JR Ritchie",
    "San Diego Padres": "Wandy Peralta",

    # Game 15: Athletics @ Giants
    "Athletics": "Aaron Civale",
    "San Francisco Giants": "Robbie Ray",
}

# From app screenshot for June 23, 2026
APP_PREDICTIONS = {
    "Zac Gallen": {"opponent": "Cardinals", "exp": 2.35},
    "Bubba Chandler": {"opponent": "Mariners", "exp": 4.11},
    "Michael McGreevy": {"opponent": "Diamondbacks", "exp": 2.45},
    "Matthew Boyd": {"opponent": "Mets", "exp": 5.20},
    "Cam Schlitter": {"opponent": "Red Sox", "exp": 6.80},
    "Christopher Sánchez": {"opponent": "Nationals", "exp": 6.58},
    "Cade Cavalli": {"opponent": "Phillies", "exp": 5.01},
    "Troy Melton": {"opponent": "Astros", "exp": 3.59},
    "Jeffrey Springs": {"opponent": "Giants", "exp": 4.42},
}

print("="*90)
print("MLB STATS API vs APP PREDICTIONS - JUNE 23, 2026")
print("="*90)

print("\nAPI RETURNED PROBABLES:")
print("-"*90)
for team, pitcher in sorted(API_PROBABLES.items()):
    print(f"{team:<30} {pitcher}")

print("\n\nAPP PREDICTED:")
print("-"*90)
for pitcher, data in APP_PREDICTIONS.items():
    print(f"{pitcher:<30} vs {data['opponent']}")

print("\n\nMATCHING CHECK:")
print("="*90)

found_matches = 0
for app_pitcher in APP_PREDICTIONS.keys():
    last_name = app_pitcher.split()[-1]
    found = False

    for team, api_pitcher in API_PROBABLES.items():
        if last_name.lower() in api_pitcher.lower():
            print(f"✓ {app_pitcher:<25} FOUND in API: {api_pitcher} ({team})")
            found = True
            found_matches += 1
            break

    if not found:
        print(f"✗ {app_pitcher:<25} NOT FOUND in API probables")

print("\n" + "="*90)
print(f"RESULT: {found_matches} / {len(APP_PREDICTIONS)} app pitchers found in API")
print("="*90)

if found_matches == 0:
    print("\n❌ COMPLETE MISMATCH")
    print("   The app is NOT using the MLB Stats API probable pitchers")
    print("   OR it's showing a different date's probables")
    print("   OR it's using cached/stale data")
