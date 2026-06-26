"""Helper to extract pitcher K data from MLB.com screenshot.

From the June 23 scoreboard screenshot, we need to find:
1. Each pitcher's name from the app predictions
2. Their actual strikeout total from the game box

Then calculate:
- Bet result (WIN/LOSS/PUSH based on OVER/UNDER vs line)
- Prediction error (abs(expected - actual))
- Hit rate for flagged bets
- MAE for all predictions

Instructions:
1. Look at MLB.com screenshot for June 23, 2026
2. For each game box, find the pitcher names and their K totals
3. Match them to the app predictions below
4. Fill in actual_k values
"""

# App predictions from screenshot
predictions = {
    "Zac Gallen": {"opponent": "Cardinals", "line": 3.5, "pick": "UNDER", "exp": 2.35, "grade": "A", "flagged": True},
    "Bubba Chandler": {"opponent": "Mariners", "line": 4.5, "pick": "UNDER", "exp": 4.11, "grade": "A", "flagged": True},
    "Michael McGreevy": {"opponent": "Diamondbacks", "line": 2.5, "pick": "UNDER", "exp": 2.45, "grade": "A", "flagged": True},
    "Matthew Boyd": {"opponent": "Mets", "line": 4.5, "pick": "OVER", "exp": 5.20, "grade": "A", "flagged": True},
    "Cam Schlitter": {"opponent": "Red Sox", "line": 6.5, "pick": "OVER", "exp": 6.80, "grade": "B", "flagged": True},
    "Christopher Sánchez": {"opponent": "Nationals", "line": 6.5, "pick": "OVER", "exp": 6.58, "grade": "B", "flagged": True},
    "Cade Cavalli": {"opponent": "Phillies", "line": 4.5, "pick": "UNDER", "exp": 5.01, "grade": "C", "flagged": True},
    "Troy Melton": {"opponent": "Astros", "line": 4.5, "pick": "UNDER", "exp": 3.59, "grade": "C", "flagged": True},
    "Jeffrey Springs": {"opponent": "Giants", "line": 4.5, "pick": "UNDER", "exp": 4.42, "grade": "C", "flagged": True},
    "Kevin Gausman": {"opponent": "Rangers", "line": 6.5, "pick": "OVER", "exp": 6.05, "flagged": False},
    "MacKenzie Gore": {"opponent": "Blue Jays", "line": 4.5, "pick": "UNDER", "exp": 5.26, "flagged": False},
    "Freddy Peralta": {"opponent": "Cubs", "line": 5.5, "pick": "UNDER", "exp": 4.54, "flagged": False},
    "Tatuya Imai": {"opponent": "Tigers", "line": 5.5, "pick": "UNDER", "exp": 5.06, "flagged": False},
    "Connelly Early": {"opponent": "Yankees", "line": 5.5, "pick": "OVER", "exp": 6.13, "flagged": False},
    "Landen Roupp": {"opponent": "Athletics", "line": 6.5, "pick": "UNDER", "exp": 5.83, "flagged": False},
}

# ACTUAL STRIKEOUTS from MLB.com screenshot (June 23, 2026)
# Extracted from visible game boxes
actual_results = {
    # Based on reading the MLB.com scoreboard screenshot
    # Some pitchers may not be visible or games postponed
    # Will fill in what can be seen from the game boxes

    # Need to identify each pitcher from the small text in game boxes
    # Game boxes show: Pitcher name, IP, K (strikeouts), ERA
    # Matching to predictions above by opponent team
}

def analyze_results():
    """Calculate betting and prediction metrics."""
    if not actual_results:
        print("No actual results entered yet!")
        print("\nLook at the MLB.com June 23 screenshot and fill in actual_results dict above.")
        print("\nGames to look for:")
        for pitcher, data in predictions.items():
            print(f"  {pitcher} vs {data['opponent']}")
        return

    print("="* 90)
    print("JUNE 23, 2026 - APP VALIDATION RESULTS")
    print("="* 90)

    print(f"\n{'PITCHER':<25} {'LINE':<6} {'PICK':<7} {'EXP':<6} {'ACT':<6} "
          f"{'BET':<6} {'ERR':<6} {'FLAG':<6}")
    print("-" * 90)

    flagged_bets = []
    all_errors = []
    flagged_errors = []
    unflagged_errors = []

    for pitcher, pred in predictions.items():
        if pitcher not in actual_results:
            print(f"{pitcher:<25} MISSING ACTUAL DATA")
            continue

        actual = actual_results[pitcher]

        # Bet result
        if pred["pick"] == "OVER" and actual > pred["line"]:
            bet_result = "WIN"
        elif pred["pick"] == "UNDER" and actual < pred["line"]:
            bet_result = "WIN"
        elif actual == pred["line"]:
            bet_result = "PUSH"
        else:
            bet_result = "LOSS"

        # Prediction error
        error = abs(pred["exp"] - actual)
        all_errors.append(error)

        if pred["flagged"]:
            flagged_bets.append(bet_result)
            flagged_errors.append(error)
            flag_str = "*"
        else:
            unflagged_errors.append(error)
            flag_str = " "

        print(f"{flag_str}{pitcher:<24} {pred['line']:<6.1f} {pred['pick']:<7} "
              f"{pred['exp']:<6.2f} {actual:<6} {bet_result:<6} {error:<6.2f} "
              f"{pred.get('grade', ''):<6}")

    # Summary
    print("\n" + "="* 90)
    print("SUMMARY")
    print("="* 90)

    # Betting performance
    if flagged_bets:
        wins = flagged_bets.count("WIN")
        losses = flagged_bets.count("LOSS")
        pushes = flagged_bets.count("PUSH")
        decided = wins + losses
        hit_rate = wins / decided if decided > 0 else 0

        print(f"\nAPP BETTING PERFORMANCE (* flagged bets):")
        print(f"  Flagged: {len(flagged_bets)}")
        print(f"  Wins: {wins}")
        print(f"  Losses: {losses}")
        print(f"  Pushes: {pushes}")
        print(f"  Hit rate: {hit_rate:.1%} (need 52.4% for -110)")

        if hit_rate >= 0.524:
            print(f"  [+] PROFITABLE")
        else:
            shortfall = 0.524 - hit_rate
            print(f"  [-] Below breakeven by {shortfall:.1%}")

    # Prediction accuracy
    if all_errors:
        mae_all = sum(all_errors) / len(all_errors)
        mae_flagged = sum(flagged_errors) / len(flagged_errors) if flagged_errors else 0
        mae_unflagged = sum(unflagged_errors) / len(unflagged_errors) if unflagged_errors else 0

        print(f"\nPURE PREDICTION ACCURACY:")
        print(f"  All pitchers: MAE = {mae_all:.3f} K")
        print(f"  Flagged: MAE = {mae_flagged:.3f} K")
        print(f"  Unflagged: MAE = {mae_unflagged:.3f} K")
        print(f"  Baseline (test set): 1.672 K")

        if mae_all < 1.672:
            print(f"  [+] Better than test average")
        else:
            print(f"  [-] Worse than test average")

        if flagged_errors and unflagged_errors and mae_flagged < mae_unflagged:
            improvement = (mae_unflagged - mae_flagged) / mae_unflagged * 100
            print(f"  [+] Flagged bets {improvement:.1f}% more accurate")
        elif flagged_errors and unflagged_errors:
            print(f"  [-] Flagged bets NOT more accurate")

    print("\n" + "="* 90)
    print("VERDICT")
    print("="* 90)

    if flagged_bets and all_errors:
        mae_all = sum(all_errors) / len(all_errors)
        wins = flagged_bets.count("WIN")
        losses = flagged_bets.count("LOSS")
        decided = wins + losses
        hit_rate = wins / decided if decided > 0 else 0

        print(f"Betting: {hit_rate:.1%} hit rate - ", end="")
        if hit_rate >= 0.524:
            print("PROFITABLE ✓")
        else:
            print("LOSING")

        print(f"Prediction: {mae_all:.3f} MAE - ", end="")
        if mae_all < 1.8:
            print("ACCURATE ✓")
        else:
            print("INACCURATE")


if __name__ == "__main__":
    analyze_results()
