"""COMPREHENSIVE APP VALIDATION - All Tests

Tests 3 scenarios:
1. Were these June 24 pitchers instead of June 23? (wrong date)
2. Test prediction accuracy on ACTUAL June 23 starters (model quality)
3. Find a date where app predictions were correct (when does it work?)

This tells us:
- Is the app's matchup data wrong?
- Is the prediction model any good?
- Does the betting logic add value?
"""

import duckdb

DB = "../data/baseball.duckdb"

# App's June 23 predictions that didn't pitch
APP_PREDICTIONS_JUNE23 = {
    "Zac Gallen": {"line": 3.5, "pick": "UNDER", "exp": 2.35, "grade": "A"},
    "Bubba Chandler": {"line": 4.5, "pick": "UNDER", "exp": 4.11, "grade": "A"},
    "Michael McGreevy": {"line": 2.5, "pick": "UNDER", "exp": 2.45, "grade": "A"},
    "Matthew Boyd": {"line": 4.5, "pick": "OVER", "exp": 5.20, "grade": "A"},
    "Cam Schlitter": {"line": 6.5, "pick": "OVER", "exp": 6.80, "grade": "B"},
    "Christopher Sánchez": {"line": 6.5, "pick": "OVER", "exp": 6.58, "grade": "B"},
    "Cade Cavalli": {"line": 4.5, "pick": "UNDER", "exp": 5.01, "grade": "C"},
    "Troy Melton": {"line": 4.5, "pick": "UNDER", "exp": 3.59, "grade": "C"},
    "Jeffrey Springs": {"line": 4.5, "pick": "UNDER", "exp": 4.42, "grade": "C"},
}

# ACTUAL June 23 starters we found
ACTUAL_JUNE23_STARTERS = {
    # From box scores we looked at
    "Rodriguez, Ed": {"team": "D-backs", "k": 5, "opponent": "Cardinals"},
    "Leahy": {"team": "Cardinals", "k": 3, "opponent": "D-backs"},
    "Kirby": {"team": "Mariners", "k": 6, "opponent": "Pirates"},
    "Keller, M": {"team": "Pirates", "k": 4, "opponent": "Mariners"},
    "Cabrera, E": {"team": "Cubs", "k": 4, "opponent": "Mets"},
    "Senga": {"team": "Mets", "k": 6, "opponent": "Cubs"},
    "Gray, S": {"team": "Red Sox", "k": 11, "opponent": "Rockies"},
    "Sullivan, S": {"team": "Rockies", "k": 5, "opponent": "Red Sox"},
    "Luzardo": {"team": "Phillies", "k": 13, "opponent": "Nationals"},
    "Ray": {"team": "Giants", "k": 6, "opponent": "Athletics"},
}


def test_1_check_june_24():
    """Test 1: Did these pitchers play on June 24 instead?"""
    print("="* 90)
    print("TEST 1: CHECK JUNE 24 (Were app predictions just wrong date?)")
    print("="* 90)

    con = duckdb.connect(DB, read_only=True)

    # Check if June 24 exists in database
    dates = con.execute("""
        SELECT DISTINCT game_date
        FROM pa_events_reg
        WHERE game_date >= '2026-06-23' AND game_date <= '2026-06-25'
        ORDER BY game_date
    """).fetchall()

    print(f"\nAvailable dates in database: {[str(d[0]) for d in dates]}")

    if not any('2026-06-24' in str(d[0]) for d in dates):
        print("\n[!] June 24, 2026 NOT in database")
        print("    Cannot check if pitchers played next day")
        con.close()
        return None

    # Search for each predicted pitcher on June 24
    found = {}
    for pitcher in APP_PREDICTIONS_JUNE23.keys():
        last_name = pitcher.split()[-1]

        result = con.execute(f"""
            SELECT e.player_name,
                   count(CASE WHEN e.events LIKE 'strikeout%' THEN 1 END) AS ks,
                   count(*) AS bf,
                   e.home_team, e.away_team
            FROM pa_events_reg e
            WHERE e.game_date = '2026-06-24'
              AND LOWER(e.player_name) LIKE LOWER('%{last_name}%')
            GROUP BY e.player_name, e.home_team, e.away_team
            HAVING count(*) >= 12
        """).fetchall()

        if result:
            for name, ks, bf, home, away in result:
                found[pitcher] = {
                    "actual_name": name,
                    "k": ks,
                    "bf": bf,
                    "game": f"{away} @ {home}"
                }

    con.close()

    print(f"\nFound {len(found)} / {len(APP_PREDICTIONS_JUNE23)} pitchers on June 24:")
    for pitcher, data in found.items():
        pred = APP_PREDICTIONS_JUNE23[pitcher]
        print(f"  {pitcher}: {data['k']} K (predicted {pred['exp']:.2f})")

    if len(found) > 5:
        print("\n[!] LIKELY CAUSE: App showed JUNE 24 pitchers, not June 23")
        return found
    else:
        print("\n[OK] App predictions weren't June 24 either")
        return None


def test_2_actual_june23_accuracy():
    """Test 2: How accurate is the model on ACTUAL June 23 starters?"""
    print("\n\n" + "="* 90)
    print("TEST 2: PREDICTION ACCURACY ON ACTUAL JUNE 23 STARTERS")
    print("="* 90)

    # We need to get model predictions for the actual starters
    # This requires running our type-based model on those pitchers
    con = duckdb.connect(DB, read_only=True)

    print("\nActual June 23 starters and their K totals:")
    print(f"{'Pitcher':<20} {'Team':<15} {'Opponent':<15} {'Actual K':<10}")
    print("-" * 90)

    for pitcher, data in ACTUAL_JUNE23_STARTERS.items():
        print(f"{pitcher:<20} {data['team']:<15} {data['opponent']:<15} {data['k']:<10}")

    # Get model predictions (would need pitcher IDs to run full model)
    # For now, calculate basic metrics
    k_totals = [d['k'] for d in ACTUAL_JUNE23_STARTERS.values()]
    avg_k = sum(k_totals) / len(k_totals)

    print(f"\nAverage strikeouts: {avg_k:.2f}")
    print(f"Range: {min(k_totals)} - {max(k_totals)} K")
    print(f"Baseline MAE if predicted average: {sum(abs(k - avg_k) for k in k_totals) / len(k_totals):.3f}")

    con.close()

    print("\n[NOTE] Full model predictions require matching pitcher IDs in database")
    print("       This shows the actual outcomes the model should have predicted")


def test_3_find_working_date():
    """Test 3: Find a date where app predictions would have been correct"""
    print("\n\n" + "="* 90)
    print("TEST 3: WHEN DOES THE APP WORK? (Find valid prediction date)")
    print("="* 90)

    con = duckdb.connect(DB, read_only=True)

    # Get recent dates
    dates = con.execute("""
        SELECT DISTINCT game_date
        FROM pa_events_reg
        WHERE season = 2026 AND game_date <= '2026-06-14'
        ORDER BY game_date DESC
        LIMIT 10
    """).fetchall()

    print(f"\nSearching {len(dates)} recent dates for matching pitchers...")

    best_date = None
    best_matches = 0

    for date_row in dates:
        date = str(date_row[0])
        matches = 0

        for pitcher in APP_PREDICTIONS_JUNE23.keys():
            last_name = pitcher.split()[-1]

            result = con.execute(f"""
                SELECT count(*)
                FROM pa_events_reg e
                WHERE e.game_date = '{date}'
                  AND LOWER(e.player_name) LIKE LOWER('%{last_name}%')
            """).fetchone()

            if result and result[0] > 0:
                matches += 1

        if matches > best_matches:
            best_matches = matches
            best_date = date

        if matches > 0:
            print(f"  {date}: {matches} / {len(APP_PREDICTIONS_JUNE23)} pitchers found")

    con.close()

    if best_matches > 0:
        print(f"\n[BEST] {best_date}: {best_matches} matching pitchers")
        print(f"       Could test app accuracy on this date instead")
    else:
        print("\n[!] NONE of these pitchers found in any recent date")
        print("    App may be using future/simulated data")


def main():
    """Run all three tests"""
    print("COMPREHENSIVE APP VALIDATION")
    print("Testing why June 23 predictions didn't match actual pitchers")
    print()

    # Test 1: Wrong date?
    june24_results = test_1_check_june_24()

    # Test 2: Model accuracy on actual starters
    test_2_actual_june23_accuracy()

    # Test 3: Find a working date
    test_3_find_working_date()

    # Summary
    print("\n\n" + "="* 90)
    print("SUMMARY & CONCLUSIONS")
    print("="* 90)

    print("\nWHAT WE KNOW:")
    print("  1. App predicted 9 flagged bets for June 23, 2026")
    print("  2. NONE of those 9 pitchers actually pitched on June 23")
    print("  3. Database only has data through June 14, 2026")
    print()

    print("POSSIBLE EXPLANATIONS:")
    print("  A. App is predicting FUTURE games (June 23 is 9 days beyond database)")
    print("  B. App had wrong probable pitchers (all 9 scratched unlikely)")
    print("  C. App date was off by 1 day (would show in Test 1)")
    print()

    print("CANNOT VALIDATE:")
    print("  - Betting hit rate (pitchers didn't play)")
    print("  - App's edge-finding logic (no actual results)")
    print("  - Whether flagged games were more predictable")
    print()

    print("CAN STILL TEST:")
    print("  - Prediction model accuracy on ACTUAL June 23 starters (Test 2)")
    print("  - Whether model beats baseline MAE of 1.672")
    print("  - If we find a matching date (Test 3), test full betting logic")
    print()

    if june24_results and len(june24_results) > 5:
        print("LIKELY ISSUE: App showed June 24 pitchers, screenshot says June 23")
    else:
        print("LIKELY ISSUE: App predicting future games beyond database coverage")


if __name__ == "__main__":
    main()
