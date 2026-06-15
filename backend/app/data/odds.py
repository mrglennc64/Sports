"""Odds-feed client behind a provider-agnostic interface.

The user holds keys for two differently-named services. The the-odds-api.com adapter
(:class:`TheOddsApiProvider`) is the default. The odds-api.io adapter
(:class:`OddsApiIoProvider`) is a fully-implemented second source selected with
``ODDS_PROVIDER=oddsapiio``; it needs a valid odds-api.io key (the UUID key shape).
The abstract ``OddsProvider`` boundary means either can be swapped in without touching
``pipeline.py``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.model.edge import decimal_to_american

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


class OddsApiIoProvider(OddsProvider):
    """Adapter for odds-api.io (the UUID-key service).

    Shape differs from the-odds-api: events are keyed by ``sport``+``league``
    slugs; odds come back grouped ``bookmakers -> [{name, odds:[{label, hdp,
    over, under}]}]`` where each prop row already carries BOTH sides at one line
    (no Over/Under pairing needed) and prices are DECIMAL strings (converted to
    American here so the downstream de-vig/Kelly stack is provider-agnostic).
    """

    BASE_URL = "https://api.odds-api.io/v3"
    SPORT = "baseball"
    LEAGUE = "usa-mlb"
    # odds-api.io expects book names in this exact casing on the request.
    IO_BOOKS = ("DraftKings", "FanDuel", "BetMGM", "Caesars", "Bovada", "BetRivers")

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        preferred_books: tuple[str, ...] = DEFAULT_BOOKS,
    ):
        if not api_key:
            raise ValueError("odds-api.io key is required")
        self._key = api_key
        self._books = preferred_books
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=15.0)

    def list_events(self) -> list[OddsEvent]:
        resp = self._client.get(
            "/events",
            params={"apiKey": self._key, "sport": self.SPORT, "league": self.LEAGUE},
        )
        resp.raise_for_status()
        return [
            OddsEvent(
                event_id=str(e.get("id", "")),
                home_team=e.get("home", ""),
                away_team=e.get("away", ""),
                commence_time=e.get("date", ""),
            )
            for e in resp.json()
        ]

    def _fetch_odds(self, event_id: str) -> dict:
        resp = self._client.get(
            "/odds",
            params={
                "apiKey": self._key,
                "eventId": event_id,
                "bookmakers": ",".join(self.IO_BOOKS),
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get_strikeout_props(self, event_id: str) -> list[PropLine]:
        # Index strikeout rows by normalized book key, then take the first
        # complete row per pitcher in preferred-book order (mirrors the-odds-api).
        by_book = self._strikeout_rows_by_book(self._fetch_odds(event_id))
        ordered = [b for b in self._books if b in by_book]
        ordered += [b for b in by_book if b not in self._books]

        out: dict[str, PropLine] = {}
        for book in ordered:
            for pitcher, line, over, under in by_book[book]:
                if pitcher not in out:  # keep most-preferred book's price
                    out[pitcher] = PropLine(pitcher, line, over, under, book)
        return list(out.values())

    def get_strikeout_quotes(self, event_id: str) -> dict[str, list[BookPrice]]:
        by_book = self._strikeout_rows_by_book(self._fetch_odds(event_id))
        out: dict[str, list[BookPrice]] = {}
        for book, rows in by_book.items():
            for pitcher, line, over, under in rows:
                out.setdefault(pitcher, []).append(BookPrice(book, line, over, under))
        return out

    def _strikeout_rows_by_book(
        self, payload: dict
    ) -> dict[str, list[tuple[str, float, float, float]]]:
        """{normalized_book: [(pitcher, line, over_american, under_american)]}."""
        out: dict[str, list[tuple[str, float, float, float]]] = {}
        for raw_book, markets in (payload.get("bookmakers") or {}).items():
            book = _norm_io_book(raw_book)
            for market in markets or []:
                if "strikeout" not in (market.get("name") or "").lower():
                    continue
                for o in market.get("odds") or []:
                    row = _parse_io_row(o)
                    if row is not None:
                        out.setdefault(book, []).append(row)
        return out


def _norm_io_book(name: str) -> str:
    """odds-api.io 'DraftKings' -> the-odds-api-style 'draftkings' key."""
    return (name or "").lower().replace(" ", "")


def _parse_io_row(o: dict) -> tuple[str, float, float, float] | None:
    """One {label, hdp, over, under} row -> (pitcher, line, over_am, under_am).

    Skips rows missing a name, line, or either side (de-vig needs the pair).
    Decimal price strings are converted to American.
    """
    pitcher = o.get("label")
    point = o.get("hdp")
    if not pitcher or point is None:
        return None
    over_am = _io_price_to_american(o.get("over"))
    under_am = _io_price_to_american(o.get("under"))
    if over_am is None or under_am is None:
        return None
    try:
        line = float(point)
    except (TypeError, ValueError):
        return None
    return pitcher, line, over_am, under_am


def _io_price_to_american(price) -> float | None:
    """Decimal odds (string or number) -> American; None if unusable."""
    try:
        dec = float(price)
    except (TypeError, ValueError):
        return None
    if dec <= 1.0:
        return None
    return decimal_to_american(dec)


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
        return OddsApiIoProvider(io_key)
    raise ValueError(f"unknown odds provider: {provider!r}")
