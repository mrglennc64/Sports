"""Tests for the cross-book arbitrage scanner."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.data.odds import BookPrice, OddsEvent, OddsProvider, PropLine, TheOddsApiProvider
from app.model.arb import (
    BookQuote,
    scan_pitcher,
    scan_quotes,
    split_stakes,
    two_way_arb_value,
)
from app.model.edge import american_to_decimal


# --------------------------------------------------------------------------- #
# Pure engine
# --------------------------------------------------------------------------- #
def test_two_way_arb_value_detects_arb():
    # +120 / +110 -> decimals 2.20 / 2.10 -> 0.4545 + 0.4762 = 0.9307 < 1.
    av = two_way_arb_value(american_to_decimal(120), american_to_decimal(110))
    assert av < 1.0
    # -110 both sides -> 0.524 * 2 > 1, no arb.
    assert two_way_arb_value(american_to_decimal(-110), american_to_decimal(-110)) > 1.0


def test_split_stakes_equalises_payout():
    dec_o, dec_u = american_to_decimal(120), american_to_decimal(110)
    so, su = split_stakes(100.0, dec_o, dec_u)
    assert so + su == pytest.approx(100.0)
    assert so * dec_o == pytest.approx(su * dec_u)  # locked: same payout either way


def test_scan_pitcher_finds_cross_book_arb():
    quotes = [
        BookQuote("fanduel", 6.5, over_odds=120, under_odds=-140),
        BookQuote("draftkings", 6.5, over_odds=-150, under_odds=110),
    ]
    opp = scan_pitcher("Ace", quotes, bankroll=100.0)
    assert opp is not None
    assert opp.arb_value < 1.0
    assert opp.guaranteed_profit > 0
    assert opp.cross_book is True
    # Best over is FanDuel (+120), best under is DraftKings (+110).
    legs = {leg.side: leg for leg in opp.legs}
    assert legs["over"].bookmaker == "fanduel"
    assert legs["under"].bookmaker == "draftkings"
    assert legs["over"].payout == pytest.approx(legs["under"].payout, abs=0.05)


def test_scan_pitcher_no_arb_returns_none():
    quotes = [
        BookQuote("fanduel", 6.5, over_odds=-110, under_odds=-110),
        BookQuote("draftkings", 6.5, over_odds=-115, under_odds=-105),
    ]
    assert scan_pitcher("Ace", quotes) is None


def test_scan_pitcher_requires_same_line():
    # Great over at 6.5 (book A) and great under at 7.5 (book B) is a MIDDLE,
    # not a locked arb — they must not be paired across different lines.
    quotes = [
        BookQuote("fanduel", 6.5, over_odds=120, under_odds=-200),
        BookQuote("draftkings", 7.5, over_odds=-200, under_odds=120),
    ]
    assert scan_pitcher("Ace", quotes) is None


def test_min_profit_pct_filters_thin_edges():
    quotes = [
        BookQuote("fanduel", 6.5, over_odds=105, under_odds=-130),
        BookQuote("draftkings", 6.5, over_odds=-130, under_odds=102),
    ]
    loose = scan_pitcher("Ace", quotes, min_profit_pct=0.0)
    assert loose is not None
    # Demand an implausibly large locked profit -> filtered out.
    assert scan_pitcher("Ace", quotes, min_profit_pct=0.50) is None


def test_scan_quotes_ranks_by_profit():
    data = {
        "Small": [
            BookQuote("a", 6.5, over_odds=101, under_odds=-115),
            BookQuote("b", 6.5, over_odds=-115, under_odds=101),
        ],
        "Big": [
            BookQuote("a", 5.5, over_odds=150, under_odds=-120),
            BookQuote("b", 5.5, over_odds=-120, under_odds=150),
        ],
    }
    opps = scan_quotes(data)
    assert [o.pitcher for o in opps] == ["Big", "Small"]


# --------------------------------------------------------------------------- #
# Odds layer: multi-book quote parsing
# --------------------------------------------------------------------------- #
def test_theoddsapi_parse_quotes_keeps_all_books():
    provider = TheOddsApiProvider(api_key="x")
    payload = {
        "bookmakers": [
            {"key": "fanduel", "markets": [{"key": "pitcher_strikeouts", "outcomes": [
                {"name": "Over", "description": "Ace", "point": 6.5, "price": 120},
                {"name": "Under", "description": "Ace", "point": 6.5, "price": -140},
            ]}]},
            {"key": "draftkings", "markets": [{"key": "pitcher_strikeouts", "outcomes": [
                {"name": "Over", "description": "Ace", "point": 6.5, "price": -150},
                {"name": "Under", "description": "Ace", "point": 6.5, "price": 110},
            ]}]},
        ]
    }
    quotes = provider._parse_quotes(payload)
    assert set(b.bookmaker for b in quotes["Ace"]) == {"fanduel", "draftkings"}


def test_default_quotes_fallback_wraps_props():
    class OneBook(OddsProvider):
        def list_events(self):
            return []

        def get_strikeout_props(self, event_id):
            return [PropLine("Ace", 6.5, 120, -140, "fanduel")]

    quotes = OneBook().get_strikeout_quotes("e1")
    assert quotes["Ace"] == [BookPrice("fanduel", 6.5, 120, -140)]


# --------------------------------------------------------------------------- #
# Pipeline: provider -> merged quotes -> ranked opportunities
# --------------------------------------------------------------------------- #
def test_scan_arbitrage_pipeline_with_fake_provider():
    from app.arb_pipeline import scan_arbitrage

    class FakeProvider(OddsProvider):
        def list_events(self):
            return [OddsEvent("e1", "", "", ""), OddsEvent("e2", "", "", "")]

        def get_strikeout_props(self, event_id):
            return []

        def get_strikeout_quotes(self, event_id):
            if event_id == "e1":  # an arb
                return {"Ace": [
                    BookPrice("fanduel", 6.5, 120, -140),
                    BookPrice("draftkings", 6.5, -150, 110),
                ]}
            return {"NoEdge": [  # no arb
                BookPrice("fanduel", 5.5, -110, -110),
            ]}

    out = scan_arbitrage(bankroll=200.0, provider=FakeProvider())
    assert out["bankroll"] == 200.0
    assert out["count"] == 1
    assert out["opportunities"][0]["pitcher"] == "Ace"
    assert out["opportunities"][0]["cross_book"] is True


# --------------------------------------------------------------------------- #
# Route wiring
# --------------------------------------------------------------------------- #
def test_v2_arb_route(monkeypatch):
    def fake(*, bankroll, min_profit_pct):
        return {"bankroll": bankroll, "min_profit_pct": min_profit_pct, "count": 0, "opportunities": []}

    monkeypatch.setattr(main, "scan_arbitrage", fake)
    client = TestClient(main.app)
    r = client.get("/v2/arb", params={"bankroll": 250, "min_profit_pct": 0.02})
    assert r.status_code == 200
    body = r.json()
    assert body["bankroll"] == 250
    assert body["min_profit_pct"] == 0.02
    assert body["count"] == 0
