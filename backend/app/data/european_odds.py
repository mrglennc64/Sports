"""Custom web scrapers + CSV importer for European sportsbooks (Betano, bet365, Unibet).

Since these books are not available via the-odds-api.com (which covers only US-regulated
markets), we provide:

1. **CSV Importer** (CsvOddsProvider): For immediate testing. You export today's strikeout
   lines from Betano/bet365/Unibet manually into a CSV, and the system ingests it. Format:
   pitcher_name, line (float), over_odds (decimal), under_odds (decimal), bookmaker

2. **Live Scrapers**: HTML/JavaScript scrapers to extract strikeout props automatically.
   Each scraper:
   - Navigates to the book's MLB strikeout prop market
   - Extracts pitcher name, line (e.g., 5.5), and decimal odds
   - Converts decimal to American odds for consistency with downstream de-vig/Kelly stack
   - Returns OddsProvider-compatible PropLine objects

The scrapers use httpx + BeautifulSoup for static HTML, or Playwright for JS rendering.
Configuration is pulled from environment variables (BETANO_EMAIL, etc.) to keep reusable.

This module can be swapped into the odds.py provider interface by setting
ODDS_PROVIDER=csv|betano|bet365|unibet in config.
"""
from __future__ import annotations

import csv
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.model.edge import decimal_to_american
from .odds import BookPrice, OddsEvent, OddsProvider, PropLine

logger = logging.getLogger(__name__)


# ============================================================================
# CSV IMPORTER (for tonight's manual validation)
# ============================================================================


class CsvOddsProvider(OddsProvider):
    """Odds provider that reads strikeout props from a CSV file.

    Use this for immediate testing: export Betano/bet365/Unibet strikeout lines
    manually to CSV, then load them here. Format:

        pitcher_name,line,over_odds,under_odds,bookmaker
        Sale,5.5,1.95,1.85,betano
        Crochet,5.5,1.92,1.88,bet365
        ...

    where over_odds and under_odds are DECIMAL odds (European format).
    They're automatically converted to American odds for the downstream pipeline.

    Configuration: Set ODDS_CSV_PATH environment variable to the CSV file path.
    Example: ODDS_CSV_PATH=/data/betano_lines_2026-06-23.csv
    """

    def __init__(self, csv_path: str | None = None):
        """Initialize with CSV file path.

        Args:
            csv_path: Path to CSV file. If None, reads from ODDS_CSV_PATH env var.

        Raises:
            ValueError: If csv_path not provided and env var not set.
            FileNotFoundError: If CSV file doesn't exist.
        """
        self._csv_path = csv_path or os.getenv("ODDS_CSV_PATH")
        if not self._csv_path:
            raise ValueError(
                "CSV path required: pass csv_path or set ODDS_CSV_PATH env var"
            )

        path = Path(self._csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {self._csv_path}")

        logger.info(f"CsvOddsProvider initialized with {self._csv_path}")

    def list_events(self) -> list[OddsEvent]:
        """CSV importer doesn't provide events; return empty list."""
        return []

    def get_strikeout_props(self, event_id: str = "") -> list[PropLine]:
        """Read strikeout props from CSV file."""
        try:
            return self._read_csv()
        except Exception as e:
            logger.error(f"CSV read failed: {e}")
            return []

    def get_strikeout_quotes(self, event_id: str = "") -> dict[str, list[BookPrice]]:
        """All CSV quotes per pitcher (all rows per pitcher from CSV)."""
        props = self.get_strikeout_props(event_id)
        out: dict[str, list[BookPrice]] = {}
        for p in props:
            out.setdefault(p.pitcher_name, []).append(
                BookPrice(p.bookmaker, p.line, p.over_odds, p.under_odds)
            )
        return out

    def _read_csv(self) -> list[PropLine]:
        """Parse CSV and return PropLine objects.

        CSV format:
            pitcher_name,line,over_odds,under_odds,bookmaker
            Sale,5.5,1.95,1.85,betano
            ...

        where over_odds/under_odds are DECIMAL odds.
        """
        props: list[PropLine] = []
        with open(self._csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                logger.warning("CSV file is empty")
                return []

            for i, row in enumerate(reader, start=1):
                try:
                    pitcher = row.get("pitcher_name", "").strip()
                    line = float(row.get("line", 0))
                    over_decimal = float(row.get("over_odds", 0))
                    under_decimal = float(row.get("under_odds", 0))
                    bookmaker = row.get("bookmaker", "").strip()

                    if not pitcher or line <= 0 or over_decimal <= 0 or under_decimal <= 0:
                        logger.warning(
                            f"CSV row {i}: skipped (missing/invalid fields): {row}"
                        )
                        continue

                    # Convert decimal to American odds
                    over_american = decimal_to_american(over_decimal)
                    under_american = decimal_to_american(under_decimal)

                    props.append(
                        PropLine(
                            pitcher_name=pitcher,
                            line=line,
                            over_odds=over_american,
                            under_odds=under_american,
                            bookmaker=bookmaker or "csv",
                        )
                    )
                    logger.debug(
                        f"CSV row {i}: {pitcher} {line} @ {bookmaker} "
                        f"({over_decimal} → {over_american})"
                    )

                except (ValueError, KeyError) as e:
                    logger.warning(f"CSV row {i}: parse error: {e}")
                    continue

        logger.info(f"CSV: loaded {len(props)} props from {self._csv_path}")
        return props


# ============================================================================
# BETANO SCRAPER
# ============================================================================


class BetanoProvider(OddsProvider):
    """Scraper for Betano (betano.com / betano.pt / betano.es / etc.).

    Betano uses dynamic rendering. We have two options:
    1. Reverse-engineer their API calls (preferred if stateless)
    2. Use Playwright to render the page and parse the DOM

    To implement:
    - Navigate to https://www.betano.pt/baseball/mlb/ (or user's region)
    - Find the strikeout props section (usually under "Player Props")
    - Extract rows: pitcher name, line (e.g., 5.5), over odds, under odds
    - Convert decimal odds to American format

    Debugging: Run with headless=False to see what the page looks like.
    """

    BASE_URL = "https://www.betano.pt"
    BASEBALL_PATH = "/baseball/mlb/"

    def __init__(self, client: httpx.Client | None = None, headless: bool = True):
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=15.0)
        self._headless = headless
        self._playwright_imported = False
        try:
            from playwright.async_api import async_playwright
            self._playwright = async_playwright()
            self._playwright_imported = True
        except ImportError:
            logger.warning("Playwright not installed; Betano scraper disabled")

    def list_events(self) -> list[OddsEvent]:
        """Fetch today's MLB games from Betano."""
        logger.warning(
            "Betano.list_events() not yet implemented; use fallback event list"
        )
        return []

    def get_strikeout_props(self, event_id: str = "") -> list[PropLine]:
        """Scrape Betano's strikeout props for today's MLB games."""
        if not self._playwright_imported:
            logger.error("Playwright not available; cannot scrape Betano")
            return []

        try:
            props = self._scrape_with_playwright()
            logger.info(f"Betano: scraped {len(props)} props")
            return props
        except Exception as e:
            logger.error(f"Betano scrape failed: {e}")
            return []

    def get_strikeout_quotes(self, event_id: str = "") -> dict[str, list[BookPrice]]:
        """All Betano quotes per pitcher."""
        props = self.get_strikeout_props(event_id)
        out: dict[str, list[BookPrice]] = {}
        for p in props:
            out.setdefault(p.pitcher_name, []).append(
                BookPrice("betano", p.line, p.over_odds, p.under_odds)
            )
        return out

    def _scrape_with_playwright(self) -> list[PropLine]:
        """Use Playwright to load Betano's MLB page and extract strikeout props.

        Betano blocks simple HTTP requests; we use a real browser to bypass anti-bot.
        """
        import asyncio
        
        try:
            return asyncio.run(self._async_scrape_betano())
        except Exception as e:
            logger.error(f"Betano Playwright scrape failed: {e}")
            return []

    async def _async_scrape_betano(self) -> list[PropLine]:
        """Async Playwright scraper for Betano strikeout props."""
        from playwright.async_api import async_playwright
        
        props: list[PropLine] = []
        
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=self._headless)
            page = await browser.new_page()
            
            try:
                # Navigate to Betano MLB page
                logger.debug(f"Navigating to {self.BASE_URL}{self.BASEBALL_PATH}")
                await page.goto(
                    self.BASE_URL + self.BASEBALL_PATH,
                    wait_until="networkidle",
                    timeout=30000
                )
                
                # Wait for strikeout props section to load
                # Common patterns: "Strikeouts", "Pitcher Strikeouts", or "Player Props"
                await page.wait_for_selector(
                    '[data-testid*="player-prop"], [class*="prop"], [class*="strikeout"]',
                    timeout=10000
                )
                
                # Extract all strikeout prop rows
                # Betano typically uses rows with pitcher name, line, and odds
                rows = await page.query_selector_all(
                    '[data-testid*="player-prop-row"], [class*="prop-row"], '
                    '[class*="market-row"], .row'
                )
                
                logger.debug(f"Found {len(rows)} potential prop rows")
                
                for row in rows:
                    try:
                        # Try to extract pitcher name
                        pitcher_elem = await row.query_selector(
                            '[class*="player"], [class*="pitcher"], [class*="name"]'
                        )
                        if not pitcher_elem:
                            continue
                        pitcher = (await pitcher_elem.inner_text()).strip()
                        
                        # Extract line (e.g., "5.5")
                        line_elem = await row.query_selector(
                            '[class*="line"], [class*="handicap"], [class*="point"]'
                        )
                        if not line_elem:
                            continue
                        line_text = await line_elem.inner_text()
                        
                        # Try to parse line as float (e.g., "5.5" or "5.5+")
                        line_match = re.search(r'(\d+\.?\d*)', line_text)
                        if not line_match:
                            continue
                        line = float(line_match.group(1))
                        
                        # Extract over odds
                        over_elem = await row.query_selector(
                            '[class*="over"], [data-odds-type="over"]'
                        )
                        if not over_elem:
                            continue
                        over_text = await over_elem.inner_text()
                        over_match = re.search(r'(\d+\.?\d+)', over_text)
                        if not over_match:
                            continue
                        over_decimal = float(over_match.group(1))
                        
                        # Extract under odds
                        under_elem = await row.query_selector(
                            '[class*="under"], [data-odds-type="under"]'
                        )
                        if not under_elem:
                            continue
                        under_text = await under_elem.inner_text()
                        under_match = re.search(r'(\d+\.?\d+)', under_text)
                        if not under_match:
                            continue
                        under_decimal = float(under_match.group(1))
                        
                        # Convert decimal to American
                        over_american = decimal_to_american(over_decimal)
                        under_american = decimal_to_american(under_decimal)
                        
                        props.append(
                            PropLine(
                                pitcher_name=pitcher,
                                line=line,
                                over_odds=over_american,
                                under_odds=under_american,
                                bookmaker="betano",
                            )
                        )
                        logger.debug(
                            f"Extracted: {pitcher} {line}K @ {over_decimal}/{under_decimal}"
                        )
                        
                    except Exception as e:
                        logger.debug(f"Failed to extract row: {e}")
                        continue
                
                logger.info(f"Betano: extracted {len(props)} strikeout props")
                
            finally:
                await browser.close()
        
        return props


# ============================================================================
# BET365 SCRAPER
# ============================================================================


class Bet365Provider(OddsProvider):
    """Scraper for bet365 (bet365.com, bet365.es, bet365.it, etc.).

    bet365 uses heavy JavaScript rendering; we use Playwright to fetch the live
    strikeout board, then parse the DOM.
    """

    BASE_URL = "https://www.bet365.com"
    # Note: Region selection (e.g., .it, .es, .com) depends on user VPN/location

    def __init__(self, headless: bool = True):
        """Initialize with optional headless browser control.

        Args:
            headless: If True, run Playwright browser headless. Set False for debugging.
        """
        self._headless = headless
        self._playwright_imported = False
        try:
            from playwright.async_api import async_playwright

            self._playwright = async_playwright()
            self._playwright_imported = True
        except ImportError:
            logger.warning("Playwright not installed; bet365 scraper disabled")

    def list_events(self) -> list[OddsEvent]:
        """Fetch today's MLB games from bet365."""
        logger.warning("bet365.list_events() not yet implemented; use fallback event list")
        return []

    def get_strikeout_props(self, event_id: str = "") -> list[PropLine]:
        """Scrape bet365's strikeout props for today's MLB games.

        bet365 organizes props per game under "Specials" or "Player Props". We load
        the MLB sport page, find strikeout markets, and extract the props.
        """
        if not self._playwright_imported:
            logger.error("Playwright not available; cannot scrape bet365")
            return []

        try:
            props = self._scrape_with_playwright()
            logger.info(f"bet365: scraped {len(props)} props")
            return props
        except Exception as e:
            logger.error(f"bet365 scrape failed: {e}")
            return []

    def get_strikeout_quotes(self, event_id: str = "") -> dict[str, list[BookPrice]]:
        """All bet365 quotes per pitcher."""
        props = self.get_strikeout_props(event_id)
        out: dict[str, list[BookPrice]] = {}
        for p in props:
            out.setdefault(p.pitcher_name, []).append(
                BookPrice("bet365", p.line, p.over_odds, p.under_odds)
            )
        return out

    def _scrape_with_playwright(self) -> list[PropLine]:
        """Use Playwright to load bet365's MLB page and extract strikeout props."""
        import asyncio
        
        try:
            return asyncio.run(self._async_scrape_bet365())
        except Exception as e:
            logger.error(f"bet365 Playwright scrape failed: {e}")
            return []

    async def _async_scrape_bet365(self) -> list[PropLine]:
        """Async Playwright scraper for bet365 strikeout props."""
        from playwright.async_api import async_playwright
        
        props: list[PropLine] = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            page = await browser.new_page()
            
            try:
                # Navigate to bet365 baseball page (MLB or US)
                logger.debug("Navigating to bet365 baseball")
                # Try US region first
                await page.goto(
                    "https://www.bet365.com/#/AS/B11/C1/D2/E151/F83/",  # MLB
                    wait_until="networkidle",
                    timeout=30000
                )
                
                # Wait for market content
                await page.wait_for_selector(
                    '[data-uat*="prop"], [class*="market"], [class*="prop"]',
                    timeout=10000
                )
                
                # Extract strikeout prop rows
                rows = await page.query_selector_all(
                    '[data-uat*="market-row"], [class*="market-row"], '
                    '[class*="prop-row"], .row'
                )
                
                logger.debug(f"Found {len(rows)} potential rows on bet365")
                
                for row in rows:
                    try:
                        # Extract pitcher name
                        pitcher_elem = await row.query_selector(
                            '[data-uat*="event-cell"], [class*="name"], span'
                        )
                        if not pitcher_elem:
                            continue
                        pitcher = (await pitcher_elem.inner_text()).strip()
                        
                        # Skip non-pitcher rows (bet365 mixes different market types)
                        if len(pitcher) < 2 or len(pitcher) > 50:
                            continue
                        
                        # Extract line and odds (bet365 layout: pitcher name | line | odds1 | odds2)
                        odds_elems = await row.query_selector_all('[class*="odds"]')
                        if len(odds_elems) < 3:  # line + over + under
                            continue
                        
                        # Parse line
                        line_text = await odds_elems[0].inner_text()
                        line_match = re.search(r'(\d+\.?\d*)', line_text)
                        if not line_match:
                            continue
                        line = float(line_match.group(1))
                        
                        # Parse over odds (decimal)
                        over_text = await odds_elems[1].inner_text()
                        over_match = re.search(r'(\d+\.?\d+)', over_text)
                        if not over_match:
                            continue
                        over_decimal = float(over_match.group(1))
                        
                        # Parse under odds (decimal)
                        under_text = await odds_elems[2].inner_text()
                        under_match = re.search(r'(\d+\.?\d+)', under_text)
                        if not under_match:
                            continue
                        under_decimal = float(under_match.group(1))
                        
                        # Convert to American
                        over_american = decimal_to_american(over_decimal)
                        under_american = decimal_to_american(under_decimal)
                        
                        props.append(
                            PropLine(
                                pitcher_name=pitcher,
                                line=line,
                                over_odds=over_american,
                                under_odds=under_american,
                                bookmaker="bet365",
                            )
                        )
                        logger.debug(
                            f"bet365: {pitcher} {line}K @ {over_decimal}/{under_decimal}"
                        )
                        
                    except Exception as e:
                        logger.debug(f"bet365: failed to extract row: {e}")
                        continue
                
                logger.info(f"bet365: extracted {len(props)} strikeout props")
                
            finally:
                await browser.close()
        
        return props


# ============================================================================
# UNIBET SCRAPER
# ============================================================================


class UnibetProvider(OddsProvider):
    """Scraper for Unibet (unibet.com, unibet.de, unibet.se, etc.).

    Unibet is part of the Kindred Group and has similar structure to bet365.
    We use httpx + BeautifulSoup initially, upgrading to Playwright if JS rendering
    is required.

    To implement:
    - Navigate to https://www.unibet.com/betting/sports/filter!1/baseball/mlb
    - Find the strikeout props section (usually under "Player Props")
    - Extract rows: pitcher name, line, over odds, under odds
    - Convert decimal odds to American format

    Debugging: Load the page in browser and inspect the DOM structure.
    """

    BASE_URL = "https://www.unibet.com"
    BASEBALL_PATH = "/betting/sports/filter!1/baseball/mlb"

    def __init__(self, client: httpx.Client | None = None, headless: bool = True):
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=15.0)
        self._headless = headless
        self._playwright_imported = False
        try:
            from playwright.async_api import async_playwright
            self._playwright = async_playwright()
            self._playwright_imported = True
        except ImportError:
            logger.warning("Playwright not installed; Unibet scraper limited to static HTML")
        
        self._session_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def list_events(self) -> list[OddsEvent]:
        """Fetch today's MLB games from Unibet."""
        logger.warning("Unibet.list_events() not yet implemented; use fallback event list")
        return []

    def get_strikeout_props(self, event_id: str = "") -> list[PropLine]:
        """Scrape Unibet's strikeout props for today's MLB games."""
        try:
            # First try static HTML scrape with BeautifulSoup
            props = self._scrape_static_html()
            if props:
                logger.info(f"Unibet (static): scraped {len(props)} props")
                return props
            
            # Fall back to Playwright if static failed
            if self._playwright_imported:
                props = self._scrape_with_playwright()
                logger.info(f"Unibet (dynamic): scraped {len(props)} props")
                return props
            
            logger.warning("Unibet scrape: no methods available")
            return []
        except Exception as e:
            logger.error(f"Unibet scrape failed: {e}")
            return []

    def get_strikeout_quotes(self, event_id: str = "") -> dict[str, list[BookPrice]]:
        """All Unibet quotes per pitcher."""
        props = self.get_strikeout_props(event_id)
        out: dict[str, list[BookPrice]] = {}
        for p in props:
            out.setdefault(p.pitcher_name, []).append(
                BookPrice("unibet", p.line, p.over_odds, p.under_odds)
            )
        return out

    def _scrape_static_html(self) -> list[PropLine]:
        """Attempt to scrape with static HTML + BeautifulSoup."""
        try:
            resp = self._client.get(self.BASEBALL_PATH, headers=self._session_headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            
            props: list[PropLine] = []
            
            # Find all strikeout prop rows (Unibet uses various class names)
            rows = soup.find_all(
                ["div", "tr"],
                class_=re.compile(r"(prop|market|row|event)", re.I)
            )
            
            logger.debug(f"Unibet static: found {len(rows)} potential rows")
            
            for row in rows:
                try:
                    # Extract pitcher name
                    pitcher_elem = row.find(["span", "td"], class_=re.compile(r"(player|name|pitcher)", re.I))
                    if not pitcher_elem:
                        continue
                    pitcher = pitcher_elem.get_text().strip()
                    if len(pitcher) < 2 or len(pitcher) > 50:
                        continue
                    
                    # Extract line, over, under odds
                    odds_elems = row.find_all(["span", "td"], class_=re.compile(r"(odds|price|line)", re.I))
                    if len(odds_elems) < 3:
                        continue
                    
                    # Parse line
                    line_match = re.search(r'(\d+\.?\d*)', odds_elems[0].get_text())
                    if not line_match:
                        continue
                    line = float(line_match.group(1))
                    
                    # Parse over odds
                    over_match = re.search(r'(\d+\.?\d+)', odds_elems[1].get_text())
                    if not over_match:
                        continue
                    over_decimal = float(over_match.group(1))
                    
                    # Parse under odds
                    under_match = re.search(r'(\d+\.?\d+)', odds_elems[2].get_text())
                    if not under_match:
                        continue
                    under_decimal = float(under_match.group(1))
                    
                    # Convert to American
                    over_american = decimal_to_american(over_decimal)
                    under_american = decimal_to_american(under_decimal)
                    
                    props.append(
                        PropLine(
                            pitcher_name=pitcher,
                            line=line,
                            over_odds=over_american,
                            under_odds=under_american,
                            bookmaker="unibet",
                        )
                    )
                    logger.debug(f"Unibet static: {pitcher} {line}K @ {over_decimal}/{under_decimal}")
                    
                except Exception as e:
                    logger.debug(f"Unibet static: failed row: {e}")
                    continue
            
            logger.info(f"Unibet static: extracted {len(props)} props")
            return props
            
        except Exception as e:
            logger.debug(f"Unibet static HTML scrape failed: {e}")
            return []

    def _scrape_with_playwright(self) -> list[PropLine]:
        """Use Playwright for dynamic rendering on Unibet."""
        import asyncio
        
        try:
            return asyncio.run(self._async_scrape_unibet())
        except Exception as e:
            logger.error(f"Unibet Playwright scrape failed: {e}")
            return []

    async def _async_scrape_unibet(self) -> list[PropLine]:
        """Async Playwright scraper for Unibet strikeout props."""
        from playwright.async_api import async_playwright
        
        props: list[PropLine] = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._headless)
            page = await browser.new_page()
            
            try:
                logger.debug("Navigating to Unibet baseball")
                await page.goto(
                    self.BASE_URL + self.BASEBALL_PATH,
                    wait_until="networkidle",
                    timeout=30000
                )
                
                # Wait for market content
                await page.wait_for_selector(
                    '[class*="market"], [class*="prop"], [class*="row"]',
                    timeout=10000
                )
                
                # Extract prop rows
                rows = await page.query_selector_all(
                    '[class*="market-row"], [class*="prop-row"], [class*="event-row"], .row'
                )
                
                logger.debug(f"Unibet dynamic: found {len(rows)} rows")
                
                for row in rows:
                    try:
                        # Extract pitcher name
                        pitcher_elem = await row.query_selector(
                            '[class*="name"], [class*="player"], span'
                        )
                        if not pitcher_elem:
                            continue
                        pitcher = (await pitcher_elem.inner_text()).strip()
                        if len(pitcher) < 2 or len(pitcher) > 50:
                            continue
                        
                        # Extract odds elements
                        odds_elems = await row.query_selector_all(
                            '[class*="odds"], [class*="price"]'
                        )
                        if len(odds_elems) < 3:
                            continue
                        
                        # Parse line
                        line_text = await odds_elems[0].inner_text()
                        line_match = re.search(r'(\d+\.?\d*)', line_text)
                        if not line_match:
                            continue
                        line = float(line_match.group(1))
                        
                        # Parse over odds
                        over_text = await odds_elems[1].inner_text()
                        over_match = re.search(r'(\d+\.?\d+)', over_text)
                        if not over_match:
                            continue
                        over_decimal = float(over_match.group(1))
                        
                        # Parse under odds
                        under_text = await odds_elems[2].inner_text()
                        under_match = re.search(r'(\d+\.?\d+)', under_text)
                        if not under_match:
                            continue
                        under_decimal = float(under_match.group(1))
                        
                        # Convert to American
                        over_american = decimal_to_american(over_decimal)
                        under_american = decimal_to_american(under_decimal)
                        
                        props.append(
                            PropLine(
                                pitcher_name=pitcher,
                                line=line,
                                over_odds=over_american,
                                under_odds=under_american,
                                bookmaker="unibet",
                            )
                        )
                        logger.debug(f"Unibet dynamic: {pitcher} {line}K @ {over_decimal}/{under_decimal}")
                        
                    except Exception as e:
                        logger.debug(f"Unibet dynamic: failed row: {e}")
                        continue
                
                logger.info(f"Unibet dynamic: extracted {len(props)} props")
                
            finally:
                await browser.close()
        
        return props


# ============================================================================
# FACTORY & CONFIG
# ============================================================================


def get_european_provider(provider_name: str, **kwargs) -> OddsProvider | None:
    """Factory to instantiate a European odds provider by name.

    Args:
        provider_name: One of "csv", "betano", "bet365", "unibet"
        **kwargs: Provider-specific arguments (e.g., csv_path for CsvOddsProvider)

    Returns:
        Configured provider instance, or None if unknown.

    Example:
        # Use CSV importer
        provider = get_european_provider("csv", csv_path="/data/betano_lines.csv")
        
        # Use live scraper (future)
        provider = get_european_provider("betano")
    """
    providers = {
        "csv": CsvOddsProvider,
        "betano": BetanoProvider,
        "bet365": Bet365Provider,
        "unibet": UnibetProvider,
    }
    cls = providers.get(provider_name.lower())
    if not cls:
        logger.warning(f"Unknown European provider: {provider_name}")
        return None

    try:
        if provider_name.lower() == "csv":
            return cls(csv_path=kwargs.get("csv_path"))
        elif provider_name.lower() == "bet365":
            return cls(headless=kwargs.get("headless", True))
        else:
            return cls()
    except Exception as e:
        logger.error(f"Failed to initialize {provider_name}: {e}")
        return None
