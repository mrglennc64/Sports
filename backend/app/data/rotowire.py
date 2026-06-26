"""
RotoWire daily lineups scraper for probable pitchers

RotoWire has better/faster probable pitcher data than MLB Stats API.
Scrapes https://www.rotowire.com/baseball/daily-lineups.php for today's starters.
"""

import httpx
from bs4 import BeautifulSoup
from datetime import date as date_cls
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class RotoWireClient:
    """Scrapes RotoWire for probable pitchers."""

    BASE_URL = "https://www.rotowire.com/baseball/daily-lineups.php"

    async def fetch_probable_pitchers(self, target_date: str) -> List[Dict]:
        """
        Fetch probable pitchers for a specific date.

        Args:
            target_date: YYYY-MM-DD format

        Returns:
            List of dicts with: away_team, home_team, away_pitcher, home_pitcher, game_time
        """
        # RotoWire only shows today's games, so warn if requesting different date
        today = date_cls.today().isoformat()
        if target_date != today:
            logger.warning(f"RotoWire only shows today's games. Requested {target_date}, today is {today}")
            # Still fetch - user might want to see what's available

        games = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.BASE_URL)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # Find all game containers
                lineup_boxes = soup.find_all('div', class_='lineup')

                for box in lineup_boxes:
                    try:
                        # Extract teams
                        teams = box.find_all('div', class_='lineup__abbr')
                        if len(teams) < 2:
                            continue

                        away_team = teams[0].text.strip()
                        home_team = teams[1].text.strip()

                        # Extract pitchers - they're in lineup__player-highlight divs
                        pitcher_highlights = box.find_all('li', class_='lineup__player-highlight')

                        away_pitcher = None
                        home_pitcher = None

                        # First highlight is away pitcher, second is home pitcher
                        if len(pitcher_highlights) >= 2:
                            away_link = pitcher_highlights[0].find('a')
                            home_link = pitcher_highlights[1].find('a')

                            away_pitcher = away_link.text.strip() if away_link else None
                            home_pitcher = home_link.text.strip() if home_link else None

                        # Extract game time if available
                        game_time_elem = box.find('div', class_='lineup__time')
                        game_time = game_time_elem.text.strip() if game_time_elem else None

                        games.append({
                            'away_team': away_team,
                            'home_team': home_team,
                            'away_pitcher': away_pitcher,
                            'home_pitcher': home_pitcher,
                            'game_time': game_time,
                            'source': 'rotowire'
                        })

                    except Exception as e:
                        logger.warning(f"Error parsing game box: {e}")
                        continue

                logger.info(f"Fetched {len(games)} games from RotoWire")
                return games

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch RotoWire data: {e}")
            return []


async def fetch_rotowire_pitchers(target_date: str) -> List[Dict]:
    """
    Convenience function to fetch RotoWire probable pitchers.

    Args:
        target_date: YYYY-MM-DD

    Returns:
        List of game dicts with probable pitchers
    """
    client = RotoWireClient()
    return await client.fetch_probable_pitchers(target_date)


# Test the scraper
if __name__ == '__main__':
    import asyncio

    async def test():
        today = date_cls.today().isoformat()
        print(f"Fetching RotoWire lineups for {today}...")

        games = await fetch_rotowire_pitchers(today)

        print(f"\nFound {len(games)} games:\n")
        for g in games:
            print(f"{g['away_team']:4s} @ {g['home_team']:4s} | {g['away_pitcher']:25s} vs {g['home_pitcher']:25s} | {g['game_time']}")

    asyncio.run(test())
