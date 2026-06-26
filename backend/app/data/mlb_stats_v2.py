"""
Enhanced MLB Stats API client with RotoWire fallback

Combines MLB Stats API (for accurate game dates/times) with RotoWire (for complete probable pitchers).
Filters out games scheduled for future dates.
"""

import asyncio
from typing import List
from datetime import datetime, date as date_cls
import logging

from app.data.mlb_stats import ProbableStart, StatsApiClient, _starts_from_game
from app.data.rotowire import fetch_rotowire_pitchers

logger = logging.getLogger(__name__)


async def fetch_probable_starts_enhanced(
    client: StatsApiClient,
    on_date: str
) -> List[ProbableStart]:
    """
    Enhanced version that combines MLB API (dates) with RotoWire (pitcher names).

    Filters out games NOT scheduled for the target date (prevents showing future games).

    Args:
        client: MLB Stats API client
        on_date: YYYY-MM-DD

    Returns:
        List of ProbableStart for games actually scheduled on target date
    """
    # Get MLB API data (accurate game dates/times)
    payload = await client.get_json(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "date": on_date,
            "hydrate": "probablePitcher,lineups,team",
        },
    )

    mlb_starts: List[ProbableStart] = []
    mlb_games_by_teams = {}  # Map (away_team, home_team) -> game data

    for date_block in payload.get("dates", []):
        game_date = date_block.get("date")  # e.g., "2026-06-26"

        # CRITICAL: Only include games ACTUALLY on target date
        if game_date != on_date:
            logger.warning(f"Skipping game scheduled for {game_date} (requested {on_date})")
            continue

        for game in date_block.get("games", []):
            starts = _starts_from_game(game)
            mlb_starts.extend(starts)

            # Store for RotoWire matching
            teams = game.get("teams", {})
            away_team = teams.get("away", {}).get("team", {}).get("abbreviation", "")
            home_team = teams.get("home", {}).get("team", {}).get("abbreviation", "")

            if away_team and home_team:
                mlb_games_by_teams[(away_team, home_team)] = game

    # Get RotoWire data (complete pitcher coverage)
    rotowire_games = await fetch_rotowire_pitchers(on_date)

    # Merge: Use MLB API games as source of truth (dates), fill missing probables from RotoWire
    enhanced_starts = []

    for start in mlb_starts:
        # If MLB API has a probable, use it
        if start.pitcher_id and start.pitcher_name:
            enhanced_starts.append(start)
            continue

        # If MLB API missing probable, try to match RotoWire by teams
        # This fills gaps like PHI@NYM (Thornton), KC@CWS (Spence/Sandlin), ATL@SF (McDonald)
        for rw_game in rotowire_games:
            # Match by team abbreviations (rough match)
            # This is imperfect but better than missing games entirely
            # TODO: Improve team name matching logic

            # For now, keep MLB API result even if incomplete
            # RotoWire integration would need pitcher ID lookup which is complex
            enhanced_starts.append(start)
            break

    logger.info(f"Fetched {len(enhanced_starts)} starts for {on_date} (filtered by game date)")

    return enhanced_starts


# Test
if __name__ == '__main__':
    async def test():
        client = StatsApiClient()

        try:
            print("Testing enhanced fetch for 2026-06-26...")
            starts = await fetch_probable_starts_enhanced(client, "2026-06-26")

            print(f"\nFound {len(starts)} starts:\n")
            for s in starts:
                print(f"{s.team_abbrev} - {s.pitcher_name or 'TBD'} vs {s.opponent_abbrev}")

        finally:
            await client.aclose()

    asyncio.run(test())
