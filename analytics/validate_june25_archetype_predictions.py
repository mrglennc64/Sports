"""
Validate June 25 archetype predictions from screenshot

Compare screenshot predictions (WITH archetype model) to actual June 25 results.
"""

import pandas as pd

# Actual results (from MLB Stats API)
actual = pd.DataFrame([
    {'pitcher': 'Bryce Miller', 'team': 'Seattle Mariners', 'actual_k': 11},
    {'pitcher': 'Tatsuya Imai', 'team': 'Houston Astros', 'actual_k': 10},
    {'pitcher': 'Connelly Early', 'team': 'Boston Red Sox', 'actual_k': 9},
    {'pitcher': 'Cam Schlittler', 'team': 'New York Yankees', 'actual_k': 9},
    {'pitcher': 'Ian Seymour', 'team': 'Tampa Bay Rays', 'actual_k': 7},
    {'pitcher': 'Cade Cavalli', 'team': 'Washington Nationals', 'actual_k': 7},
    {'pitcher': 'Landen Roupp', 'team': 'San Francisco Giants', 'actual_k': 6},
    {'pitcher': 'Jeffrey Springs', 'team': 'Athletics', 'actual_k': 6},
    {'pitcher': 'Troy Melton', 'team': 'Detroit Tigers', 'actual_k': 6},
    {'pitcher': 'Cristopher Sánchez', 'team': 'Philadelphia Phillies', 'actual_k': 6},
    {'pitcher': 'Freddy Peralta', 'team': 'New York Mets', 'actual_k': 5},
    {'pitcher': 'MacKenzie Gore', 'team': 'Texas Rangers', 'actual_k': 5},
    {'pitcher': 'Kevin Gausman', 'team': 'Toronto Blue Jays', 'actual_k': 4},
    {'pitcher': 'Bubba Chandler', 'team': 'Pittsburgh Pirates', 'actual_k': 4},
    {'pitcher': 'Matthew Boyd', 'team': 'Chicago Cubs', 'actual_k': 4},
    {'pitcher': 'Seth Lugo', 'team': 'Kansas City Royals', 'actual_k': 3},
])

# Predictions from screenshot (WITH archetype model - June 25 date)
# Looking at screenshot, these pitchers are NOT in it (they were probables not actuals)
# Screenshot shows: Trevor Rogers, Nick Martinez, Luis Castillo, Zac Gallen, Will Warren,
#                   Spencer Arrighetti, etc.

# The screenshot shows predictions for PROBABLE pitchers, not ACTUAL starters
# This means we CAN'T validate it because most actuals aren't in the predictions

print("=" * 100)
print("JUNE 25 ARCHETYPE MODEL VALIDATION PROBLEM")
print("=" * 100)

print("\nACTUAL STARTERS (16 pitchers):")
print(actual.to_string(index=False))

print("\n" + "=" * 100)
print("SCREENSHOT ANALYSIS")
print("=" * 100)

print("""
The screenshot dated 2026-06-25 shows predictions for PROBABLE pitchers announced
before the games, NOT the actual starters.

Pitchers in screenshot:
- Trevor Rogers (Washington) - ACTUAL starter was Cade Cavalli
- Zac Gallen (Tampa Bay) - GAME POSTPONED
- Luis Castillo (Cleveland) - Not a June 25 game
- Nick Martinez (Arizona) - GAME POSTPONED
- Will Warren (Boston) - ACTUAL starter was Connelly Early
- Spencer Arrighetti (Detroit) - ACTUAL starter was Troy Melton

Issue: The app generates predictions based on scheduled/probable pitchers.
When pitchers get scratched or games postponed, the predictions don't match actuals.

SOLUTION:
We need predictions for the ACTUAL starters:
- Bryce Miller
- Tatsuya Imai
- Connelly Early
- Cam Schlittler
- Ian Seymour
- Cade Cavalli
- etc.

But the screenshot doesn't contain these predictions because they were either:
1. Not announced as probables, OR
2. Last-minute substitutions

CONCLUSION:
Cannot validate June 25 archetype predictions from this screenshot because
13/16 actual starters are NOT in the screenshot predictions.
""")

print("\n" + "=" * 100)
print("WHAT WE CAN VALIDATE")
print("=" * 100)

print("""
Option 1: Wait for June 26 games to finish tonight, then validate those predictions
          (screenshot shows June 26 predictions WITH archetype model)

Option 2: Generate June 25 predictions NOW using the archetype model in the API
          and compare to actual results (retrospective validation)

Option 3: Check if database has June 25 data and run validation script directly
""")

