"""Odds-feed client behind a provider-agnostic interface.

The user holds keys for two differently-named services. Only the the-odds-api.com
key was confirmed valid (the UUID key 401s there), so that adapter is implemented
and selected by default. The abstract ``OddsProvider`` boundary means a second
provider can be added later without touching ``pipeline.py``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

# Preferred bookmakers, in order. The first book offering a complete over/under pair
# for a pitcher is used (de-vig must use a single book's two-sided price).
DEFAULT_BOOKS = ("draftkings", "fanduel", "betmgm", "bovada", "caesars")


@dataclass
class OddsEvent:
    event_id: str
    home_team: str
    away_team: str
    commence_time: str


@dataclass
class PropLine:
    pitcher_name: str
    line: float
    over_odds: float
    under_odds: float
    bookmaker: str


@dataclass
class BookPrice:
    """One book's two-sided strikeout price for a pitcher (for arb scanning)."""

    bookmaker: str
    line: float
    over_odds: float
    under_odds: float


class OddsProvider(ABC):
    @abstractmethod
    def list_events(self) -> list[OddsEvent]: ...

    @abstractmethod
    def get_strikeout_props(self, event_id: str) -> list[PropLine]: ...

    def get_strikeout_quotes(self, event_id: str) -> dict[str, list[BookPrice]]:
        """Every book's quote per pitcher (for cross-book arbitrage).

        Default implementation derives single-book quotes from
        :meth:`get_strikeout_props`; providers that expose all books (e.g.
        the-odds-api) override this to return the full multi-book set.
        """
        out: dict[str, list[BookPrice]] = {}
        for p in self.get_strikeout_props(event_id):
            out.setdefault(p.pitcher_name, []).append(
                BookPrice(p.bookmaker, p.line, p.over_odds, p.under_odds)
            )
        return out


class TheOddsApiProvider(OddsProvider):
    BASE_URL = "https://api.the-odds-api.com/v4"
    SPORT = "baseball_mlb"
    MARKET = "pitcher_strikeouts"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        preferred_books: tuple[str, ...] = DEFAULT_BOOKS,
    ):
        if not api_key:
            raise ValueError("the-odds-api key is required")
        self._key = api_key
        self._books = preferred_books
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=15.0)

    def list_events(self) -> list[OddsEvent]:
        resp = self._client.get(
            f"/sports/{self.SPORT}/events", params={"apiKey": self._key}
        )
        resp.raise_for_status()
        return [
            OddsEvent(
                event_id=e["id"],
                home_team=e.get("home_team", ""),
                away_team=e.get("away_team", ""),
                commence_time=e.get("commence_time", ""),
            )
            for e in resp.json()
        ]

    def get_strikeout_props(self, event_id: str) -> list[PropLine]:
        resp = self._client.get(
            f"/sports/{self.SPORT}/events/{event_id}/odds",
            params={
                "apiKey": self._key,
                "regions": "us",
                "markets": self.MARKET,
                "oddsFormat": "american",
            },
        )
        resp.raise_for_status()
        return self._parse_props(resp.json())

    def get_strikeout_quotes(self, event_id: str) -> dict[str, list[BookPrice]]:
        """All books' over/under prices per pitcher for one event."""
        resp = self._client.get(
            f"/sports/{self.SPORT}/events/{event_id}/odds",
            params={
                "apiKey": self._key,
                "regions": "us",
                "markets": self.MARKET,
                "oddsFormat": "american",
            },
        )
        resp.raise_for_status()
        return self._parse_quotes(resp.json())

    def _parse_quotes(self, payload: dict) -> dict[str, list[BookPrice]]:
        out: dict[str, list[BookPrice]] = {}
        for bm in payload.get("bookmakers", []):
            book = bm.get("key", "")
            for market in bm.get("markets", []):
                if market.get("key") != self.MARKET:
                    continue
                for pitcher, (line, over, under) in _pair_outcomes(
                    market.get("outcomes", [])
                ).items():
                    out.setdefault(pitcher, []).append(
                        BookPrice(book, line, over, under)
                    )
        return out

    def _parse_props(self, payload: dict) -> list[PropLine]:
        # Index bookmakers by key for preferred-order lookup.
        by_book: dict[str, list[dict]] = {}
        for bm in payload.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") == self.MARKET:
                    by_book[bm["key"]] = market.get("outcomes", [])

        # Walk books in preference order; take the first complete pair per pitcher.
        ordered = [b for b in self._books if b in by_book]
        ordered += [b for b in by_book if b not in self._books]  # any extras

        out: dict[str, PropLine] = {}
        for book in ordered:
            pairs = _pair_outcomes(by_book[book])
            for pitcher, (line, over, under) in pairs.items():
                if pitcher not in out:  # keep first (most-preferred) book's pair
                    out[pitcher] = PropLine(
                        pitcher_name=pitcher,
                        line=line,
                        over_odds=over,
                        under_odds=under,
                        bookmaker=book,
                    )
        return list(out.values())


def _pair_outcomes(outcomes: list[dict]) -> dict[str, tuple[float, float, float]]:
    """Group Over/Under outcomes by pitcher into (line, over_odds, under_odds).

    Only pitchers with BOTH sides at the same line are returned (de-vig needs the pair).
    """
    over: dict[str, tuple[float, float]] = {}   # pitcher -> (line, price)
    under: dict[str, tuple[float, float]] = {}
    for o in outcomes:
        pitcher = o.get("description")
        side = (o.get("name") or "").lower()
        price = o.get("price")
        point = o.get("point")
        if pitcher is None or price is None or point is None:
            continue
        if side == "over":
            over[pitcher] = (point, price)
        elif side == "under":
            under[pitcher] = (point, price)

    paired: dict[str, tuple[float, float, float]] = {}
    for pitcher, (line, over_price) in over.items():
        if pitcher in under and under[pitcher][0] == line:
            paired[pitcher] = (line, over_price, under[pitcher][1])
    return paired


class UnconfiguredProvider(OddsProvider):
    """Placeholder for the second (UUID-key) service, base URL not yet confirmed."""

    def __init__(self, name: str):
        self._name = name

    def _fail(self):
        raise NotImplementedError(
            f"Odds provider {self._name!r} is not implemented yet: confirm its base URL "
            "and auth, then add an adapter here. The UUID key did not authenticate "
            "against the-odds-api.com."
        )

    def list_events(self) -> list[OddsEvent]:
        self._fail()

    def get_strikeout_props(self, event_id: str) -> list[PropLine]:
        self._fail()


def get_provider(provider: str, theoddsapi_key: str, io_key: str) -> OddsProvider:
    if provider == "theoddsapi":
        return TheOddsApiProvider(theoddsapi_key)
    if provider == "oddsapiio":
        return UnconfiguredProvider("oddsapiio")
    raise ValueError(f"unknown odds provider: {provider!r}")
