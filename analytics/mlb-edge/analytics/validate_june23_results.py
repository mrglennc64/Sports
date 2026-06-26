"""Validate June 23 app predictions once actual results are filled in.

Usage:
1. Fill in validate_june23_manual.csv with actual strikeout results
2. Run: python validate_june23_results.py

This compares:
- App betting approach (flagged bets based on edge/Kelly)
- Pure prediction approach (just accuracy, ignoring betting logic)
"""
import csv

CSV_FILE = "validate_june23_manual.csv"


def main():
    # Read results
    predictions = []
    with open(CSV_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Actual_KS"] and row["Actual_KS"].strip():
                predictions.append(row)

    if not predictions:
        print("ERROR: No actual results filled in yet.")
        print(f"Please edit {CSV_FILE} and add actual strikeout totals.")
        return

    print("="* 90)
    print(f"JUNE 23, 2026 - APP vs PURE PREDICTION VALIDATION")
    print(f"Validated: {len(predictions)} pitchers")
    print("="* 90)

    # Display results
    print(f"\n{'PITCHER':<25} {'LINE':<6} {'PICK':<7} {'EXP':<6} {'ACT':<6} "
          f"{'BET':<6} {'ERR':<6} {'FLAG':<6}")
    print("-" * 90)

    app_bets = []
    flagged_errors = []
    unflagged_errors = []

    for p in predictions:
        pitcher = p["Pitcher"]
        line = float(p["Line"])
        pick = p["Pick"]
        exp_ks = float(p["Exp_KS"])
        actual_ks = int(p["Actual_KS"])
        flagged = p["Flagged"] == "YES"

        # Bet result
        if pick == "OVER" and actual_ks > line:
            bet_result = "WIN"
        elif pick == "UNDER" and actual_ks < line:
            bet_result = "WIN"
        elif actual_ks == line:
            bet_result = "PUSH"
        else:
            bet_result = "LOSS"

        # Prediction error
        pred_error = abs(exp_ks - actual_ks)

        if flagged:
            app_bets.append(bet_result)
            flagged_errors.append(pred_error)
        else:
            unflagged_errors.append(pred_error)

        flag_str = "*" if flagged else " "
        print(f"{flag_str}{pitcher:<24} {line:<6.1f} {pick:<7} {exp_ks:<6.2f} {actual_ks:<6} "
              f"{bet_result:<6} {pred_error:<6.2f} {flag_str}")

    # Summary
    print("\n" + "="* 90)
    print("RESULTS SUMMARY")
    print("="* 90)

    # App betting performance
    if app_bets:
        wins = app_bets.count("WIN")
        losses = app_bets.count("LOSS")
        pushes = app_bets.count("PUSH")
        decided = wins + losses
        hit_rate = wins / decided if decided > 0 else 0

        print(f"\nAPP BETTING PERFORMANCE (* flagged bets):")
        print(f"  Total flagged: {len(app_bets)}")
        print(f"  Wins: {wins}")
        print(f"  Losses: {losses}")
        print(f"  Pushes: {pushes}")
        print(f"  Hit rate: {hit_rate:.1%} (need ~52.4% for -110 juice)")

        if hit_rate >= 0.524:
            print(f"  [+] PROFITABLE at standard juice")
        else:
            print(f"  [-] Below breakeven")

    # Pure prediction accuracy
    all_errors = flagged_errors + unflagged_errors
    mae_all = sum(all_errors) / len(all_errors) if all_errors else 0
    mae_flagged = sum(flagged_errors) / len(flagged_errors) if flagged_errors else 0
    mae_unflagged = sum(unflagged_errors) / len(unflagged_errors) if unflagged_errors else 0

    print(f"\nPURE PREDICTION ACCURACY:")
    print(f"  All pitchers ({len(predictions)}): MAE = {mae_all:.3f} K")
    print(f"  Flagged ({len(flagged_errors)}): MAE = {mae_flagged:.3f} K")
    print(f"  Unflagged ({len(unflagged_errors)}): MAE = {mae_unflagged:.3f} K")

    if mae_flagged < mae_unflagged:
        improvement = (mae_unflagged - mae_flagged) / mae_unflagged * 100
        print(f"  [+] Flagged games {improvement:.1f}% more accurate")
        print(f"      App correctly identified the MORE PREDICTABLE games")
    else:
        print(f"  [-] Flagged games were NOT more predictable")

    # Compare to baseline MAE
    baseline_mae = 1.672  # From our tests
    print(f"\nVS BASELINE MODEL:")
    print(f"  Test set average MAE: {baseline_mae:.3f} K")
    print(f"  June 23 actual MAE: {mae_all:.3f} K")

    if mae_all < baseline_mae:
        print(f"  [+] Better than test average")
    else:
        print(f"  [-] Worse than test average (normal day-to-day variance)")

    print("\n" + "="* 90)
    print("INTERPRETATION")
    print("="* 90)
    print("This compares TWO different questions:")
    print()
    print("1. APP BETTING: Did the edge-flagged bets win?")
    print("   - Uses odds, expected value, Kelly criterion")
    print("   - Success = hit rate > 52.4% (beat the juice)")
    print()
    print("2. PURE PREDICTION: How accurate were the K forecasts?")
    print("   - Ignores odds and betting entirely")
    print("   - Success = low MAE (close to 1.67 baseline)")
    print()
    print("You can have:")
    print("  - Good predictions but bad betting (accurate but no edge)")
    print("  - Bad predictions but good betting (got lucky on flagged games)")
    print("  - Both good (accurate AND found +EV spots)")
    print("  - Both bad (inaccurate AND lost money)")


if __name__ == "__main__":
    main()
