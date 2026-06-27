"""Compare lineup K% old (overall) vs new (handedness split) for today's slate.

Shows the delta between the two approaches for each game where a lineup is posted.
No odds API needed — uses only the free MLB Stats API.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from datetime import date
from app.data.client import StatsApiClient
from app.data.mlb_stats import (
    fetch_probable_starts,
    fetch_lineup_strength,
    fetch_pitcher_form,
    fetch_pitcher_workload,
)
from app.model.inputs import Handedness

TODAY = date.today().isoformat()
MLB_API = "https://statsapi.mlb.com"


async def run():
    async with StatsApiClient() as client:
        starts = await fetch_probable_starts(client, TODAY)

        print(f"Today's slate: {TODAY}  ({len(starts)} probable starters)\n")
        print(f"{'Pitcher':<24} {'Hand':<4} {'Opponent':<26} {'Overall K%':>10} {'Split K%':>9} {'Delta':>7}")
        print("-" * 85)

        results = []
        for start in starts:
            if start.pitcher_id is None:
                continue

            season = int(TODAY[:4])
            pitcher_hand = start.throws

            # Overall lineup K% (old method)
            lu_overall = await fetch_lineup_strength(
                client, start.game_pk,
                opponent_is_home=not start.is_home,
                season=season,
                pitcher_hand=None,
            )

            # Handedness-split lineup K% (new method)
            lu_split = await fetch_lineup_strength(
                client, start.game_pk,
                opponent_is_home=not start.is_home,
                season=season,
                pitcher_hand=pitcher_hand,
            )

            if lu_overall is None and lu_split is None:
                overall_pct = None
                split_pct = None
                delta = None
                overall_str = "no lineup"
                split_str   = "no lineup"
                delta_str   = ""
            else:
                overall_pct = lu_overall.projected_lineup_k_pct if lu_overall else None
                split_pct   = lu_split.projected_lineup_k_pct   if lu_split   else None
                delta = (split_pct - overall_pct) if (split_pct is not None and overall_pct is not None) else None
                overall_str = f"{overall_pct:.1%}" if overall_pct is not None else "—"
                split_str   = f"{split_pct:.1%}"   if split_pct   is not None else "—"
                delta_str   = f"{delta:+.1%}"      if delta        is not None else ""

            hand_str = pitcher_hand.value if pitcher_hand else "?"
            results.append((start.pitcher_name, hand_str, start.opponent_team_name,
                            overall_str, split_str, delta_str, delta))

            print(f"{start.pitcher_name:<24} {hand_str:<4} {start.opponent_team_name:<26} "
                  f"{overall_str:>10} {split_str:>9} {delta_str:>7}")

        # Summary
        deltas = [r[6] for r in results if r[6] is not None]
        if deltas:
            avg = sum(deltas) / len(deltas)
            max_d = max(deltas)
            min_d = min(deltas)
            print()
            print(f"Lineups posted: {len(deltas)}/{len(results)}")
            print(f"Avg delta:  {avg:+.2%}  |  Range: {min_d:+.2%} to {max_d:+.2%}")
            print()
            print("A negative delta = lineup strikes out LESS vs this pitcher's arm than")
            print("their overall rate suggests. Positive = more strikeout prone vs this arm.")


if __name__ == "__main__":
    asyncio.run(run())
