"""Compare app betting recommendations vs pure prediction accuracy.

Tests June 23, 2026 (from screenshot):
- App flagged 9 bets based on edge/Kelly/odds
- Pure prediction just looks at expected K vs actual K (no betting logic)

Question: Which approach was more accurate?

Run: python app_vs_prediction_test.py
"""
from __future__ import annotations

import duckdb

DB = "../data/baseball.duckdb"
TARGET_DATE = "2026-06-23"

# From screenshot - app predictions for 2026-06-23
APP_PREDICTIONS = [
    # (pitcher_name, opponent, line, pick, exp_ks, grade, flagged)
    ("Zac Gallen", "St. Louis Cardinals", 3.5, "UNDER", 2.35, "A", True),
    ("Bubba Chandler", "Seattle Mariners", 4.5, "UNDER", 4.11, "A", True),
    ("Michael McGreevy", "Arizona Diamondbacks", 2.5, "UNDER", 2.45, "A", True),
    ("Matthew Boyd", "New York Mets", 4.5, "OVER", 5.20, "A", True),
    ("Cam Schlitter", "Boston Red Sox", 6.5, "OVER", 6.80, "B", True),
    ("Christopher Sánchez", "Washington Nationals", 6.5, "OVER", 6.58, "B", True),
    ("Cade Cavalli", "Philadelphia Phillies", 4.5, "UNDER", 5.01, "C", True),
    ("Troy Melton", "Houston Astros", 4.5, "UNDER", 3.59, "C", True),
    ("Jeffrey Springs", "San Francisco Giants", 4.5, "UNDER", 4.42, "C", True),
    ("Kevin Gausman", "Texas Rangers", 6.5, "OVER", 6.05, "", False),
    ("MacKenzie Gore", "Toronto Blue Jays", 4.5, "UNDER", 5.26, "", False),
    ("Freddy Peralta", "Chicago Cubs", 5.5, "UNDER", 4.54, "", False),
    ("Tatuya Imai", "Detroit Tigers", 5.5, "UNDER", 5.06, "", False),
    ("Connelly Early", "New York Yankees", 5.5, "OVER", 6.13, "", False),
    ("Landen Roupp", "Athletics", 6.5, "UNDER", 5.83, "", False),
]


def main() -> None:
    con = duckdb.connect(DB, read_only=True)

    print("="* 90)
    print(f"APP vs PURE PREDICTION TEST - {TARGET_DATE}")
    print("="* 90)

    # Get actual results for this date
    results = {}
    for pitcher_name, opponent, line, pick, exp_ks, grade, flagged in APP_PREDICTIONS:
        # Try to find this pitcher's game on this date
        rows = con.execute(f"""
            SELECT e.pitcher, e.player_name, e.game_pk,
                   count(*) FILTER (WHERE e.events LIKE 'strikeout%') AS actual_ks,
                   count(*) AS batters_faced,
                   e.home_team, e.away_team
            FROM pa_events_reg e
            WHERE e.game_date = '{TARGET_DATE}'
              AND LOWER(e.player_name) LIKE LOWER('%{pitcher_name.split()[-1]}%')
            GROUP BY e.pitcher, e.player_name, e.game_pk, e.home_team, e.away_team
        """).fetchall()

        if rows:
            for pid, pname, gpk, actual_ks, bf, home, away in rows:
                # Check opponent match
                opp_short = opponent.split()[-1].upper()  # e.g., "CARDINALS"
                if opp_short in home.upper() or opp_short in away.upper():
                    results[pitcher_name] = {
                        "actual_ks": actual_ks,
                        "bf": bf,
                        "full_name": pname,
                        "game": f"{away} @ {home}"
                    }
                    break

    con.close()

    # Analyze results
    print(f"\n{'PITCHER':<25} {'LINE':<6} {'PICK':<7} {'EXP':<6} {'ACT':<6} "
          f"{'BET':<6} {'PRED':<6} {'GRADE':<6}")
    print("-" * 90)

    app_bets_correct = 0
    app_bets_total = 0
    pred_errors = []
    app_flagged_errors = []
    app_unflagged_errors = []

    for pitcher_name, opponent, line, pick, exp_ks, grade, flagged in APP_PREDICTIONS:
        if pitcher_name not in results:
            print(f"{pitcher_name:<25} {line:<6} {pick:<7} {exp_ks:<6.2f} {'???':<6} "
                  f"{'???':<6} {'???':<6} {grade:<6} NO DATA")
            continue

        actual = results[pitcher_name]["actual_ks"]
        bf = results[pitcher_name]["bf"]

        # App betting result
        if flagged:
            app_bets_total += 1
            if pick == "OVER" and actual > line:
                bet_result = "WIN"
                app_bets_correct += 1
            elif pick == "UNDER" and actual < line:
                bet_result = "WIN"
                app_bets_correct += 1
            elif actual == line:
                bet_result = "PUSH"
            else:
                bet_result = "LOSS"
        else:
            bet_result = "N/A"

        # Pure prediction error
        pred_error = abs(exp_ks - actual)
        pred_errors.append(pred_error)

        if flagged:
            app_flagged_errors.append(pred_error)
        else:
            app_unflagged_errors.append(pred_error)

        # Would pure prediction have been correct?
        if exp_ks > line and actual > line:
            pred_result = "RIGHT"
        elif exp_ks < line and actual < line:
            pred_result = "RIGHT"
        elif abs(exp_ks - line) < 0.3:  # Too close to call
            pred_result = "NEUTRAL"
        else:
            pred_result = "WRONG"

        flag_marker = "*" if flagged else " "
        print(f"{flag_marker}{pitcher_name:<24} {line:<6.1f} {pick:<7} {exp_ks:<6.2f} {actual:<6} "
              f"{bet_result:<6} {pred_result:<6} {grade:<6} (BF={bf})")

    # Summary
    print("\n" + "="* 90)
    print("SUMMARY")
    print("="* 90)

    if app_bets_total > 0:
        app_hit_rate = app_bets_correct / app_bets_total
        print(f"\nAPP BETTING PERFORMANCE (flagged bets only, * marked):")
        print(f"  Total bets: {app_bets_total}")
        print(f"  Wins: {app_bets_correct}")
        print(f"  Hit rate: {app_hit_rate:.1%}")

    if pred_errors:
        mae_all = sum(pred_errors) / len(pred_errors)
        print(f"\nPURE PREDICTION ACCURACY (all {len(pred_errors)} pitchers):")
        print(f"  MAE: {mae_all:.3f} K")

    if app_flagged_errors:
        mae_flagged = sum(app_flagged_errors) / len(app_flagged_errors)
        print(f"\nPREDICTION ACCURACY - FLAGGED BETS ONLY ({len(app_flagged_errors)} pitchers):")
        print(f"  MAE: {mae_flagged:.3f} K")

    if app_unflagged_errors:
        mae_unflagged = sum(app_unflagged_errors) / len(app_unflagged_errors)
        print(f"\nPREDICTION ACCURACY - UNFLAGGED ({len(app_unflagged_errors)} pitchers):")
        print(f"  MAE: {mae_unflagged:.3f} K")

    print("\n" + "="* 90)
    print("INTERPRETATION")
    print("="* 90)
    print("BET column = did the app's OVER/UNDER pick win the bet?")
    print("PRED column = was prediction on correct side of line (ignoring odds/edge)?")
    print()
    print("App uses edge/Kelly/odds to FLAG bets (marked with *)")
    print("Pure prediction just looks at: was EXP_KS close to ACTUAL_KS?")
    print()
    if app_bets_total > 0 and pred_errors:
        print(f"App betting hit rate: {app_hit_rate:.1%}")
        print(f"Pure prediction MAE: {mae_all:.3f} K")
        print()
        if app_hit_rate < 0.53:
            print("[!] App hit rate below breakeven (~52.4% for -110 juice)")
        if mae_flagged < mae_unflagged:
            print("[+] App correctly flagged the MORE PREDICTABLE games")
        else:
            print("[-] Flagged games were NOT more predictable than unflagged")


if __name__ == "__main__":
    main()
