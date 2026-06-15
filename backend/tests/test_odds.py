import httpx
import pytest
import respx

from app.data.names import names_match, normalize_name
from app.data.odds import (
    OddsApiIoProvider,
    TheOddsApiProvider,
    UnconfiguredProvider,
    get_provider,
)

IO_BASE = "https://api.odds-api.io/v3"

BASE = "https://api.the-odds-api.com/v4"


# --- name matching ------------------------------------------------------------

def test_normalize_strips_accents_and_case():
    assert normalize_name("José Ramírez") == "jose ramirez"


def test_names_match_accents_and_suffix():
    assert names_match("José Ramírez", "Jose Ramirez")
    assert names_match("Luis Ortiz Jr.", "Luis Ortiz")


def test_names_match_middle_initial():
    assert names_match("Luis L. Ortiz", "Luis Ortiz")


def test_names_no_false_match():
    assert not names_match("Aaron Nola", "Aaron Judge")
    assert not names_match("", "Aaron Nola")


# --- odds parsing -------------------------------------------------------------

PROPS_PAYLOAD = {
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [
                        {"name": "Over", "description": "Aaron Nola", "price": -125, "point": 5.5},
                        {"name": "Under", "description": "Aaron Nola", "price": -105, "point": 5.5},
                        {"name": "Over", "description": "Bryce Elder", "price": -142, "point": 4.5},
                        {"name": "Under", "description": "Bryce Elder", "price": 116, "point": 4.5},
                    ],
                }
            ],
        }
    ]
}


@respx.mock
def test_list_events():
    respx.get(f"{BASE}/sports/baseball_mlb/events").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "home_team": "Atlanta Braves",
                    "away_team": "Pittsburgh Pirates",
                    "commence_time": "2026-06-07T17:36:00Z",
                }
            ],
        )
    )
    p = TheOddsApiProvider("KEY", client=httpx.Client(base_url=BASE))
    events = p.list_events()
    assert len(events) == 1
    assert events[0].event_id == "abc"
    assert events[0].home_team == "Atlanta Braves"


@respx.mock
def test_get_strikeout_props_pairs_sides():
    respx.get(f"{BASE}/sports/baseball_mlb/events/abc/odds").mock(
        return_value=httpx.Response(200, json=PROPS_PAYLOAD)
    )
    p = TheOddsApiProvider("KEY", client=httpx.Client(base_url=BASE))
    props = p.get_strikeout_props("abc")
    by_name = {pl.pitcher_name: pl for pl in props}
    assert by_name["Aaron Nola"].line == 5.5
    assert by_name["Aaron Nola"].over_odds == -125
    assert by_name["Aaron Nola"].under_odds == -105
    assert by_name["Aaron Nola"].bookmaker == "draftkings"
    assert by_name["Bryce Elder"].under_odds == 116


@respx.mock
def test_props_drops_unpaired_side():
    payload = {
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            # only an Over, no matching Under -> dropped
                            {"name": "Over", "description": "Lonely Arm", "price": -120, "point": 6.5},
                        ],
                    }
                ],
            }
        ]
    }
    respx.get(f"{BASE}/sports/baseball_mlb/events/x/odds").mock(
        return_value=httpx.Response(200, json=payload)
    )
    p = TheOddsApiProvider("KEY", client=httpx.Client(base_url=BASE))
    assert p.get_strikeout_props("x") == []


def test_get_provider_selection():
    assert isinstance(get_provider("theoddsapi", "hex", ""), TheOddsApiProvider)
    assert isinstance(get_provider("oddsapiio", "", "uuid"), OddsApiIoProvider)
    with pytest.raises(ValueError):
        get_provider("nope", "", "")


def test_theoddsapi_requires_key():
    with pytest.raises(ValueError):
        TheOddsApiProvider("")


# --- odds-api.io adapter ------------------------------------------------------

# Mirrors the LIVE odds-api.io shape (verified 2026-06-15): all props sit in one
# market named "Player Props"; the prop TYPE is in each row's label as
# "Pitcher Name (Prop Type)". Pitcher Ks = "(Pitcher Strikeouts)" (two-sided);
# batter Ks = "(Total Strikeouts)" (often over-only) and must be excluded. Prices
# are DECIMAL strings. DraftKings is more preferred than FanDuel in DEFAULT_BOOKS.
IO_PROPS_PAYLOAD = {
    "id": 123,
    "home": "Philadelphia Phillies",
    "away": "Atlanta Braves",
    "bookmakers": {
        "FanDuel": [
            {
                "name": "Player Props",
                "odds": [
                    {"label": "Aaron Nola (Pitcher Strikeouts)", "hdp": 5.5, "over": "1.95", "under": "1.85"}
                ],
            }
        ],
        "DraftKings": [
            {
                "name": "Player Props",
                "odds": [
                    {"label": "Aaron Nola (Pitcher Strikeouts)", "hdp": 5.5, "over": "2.00", "under": "1.80"},
                    {"label": "Bryce Elder (Pitcher Strikeouts)", "hdp": 4.5, "over": "1.90", "under": "1.90"},
                    # batter strikeout prop -> excluded (wrong type, over-only)
                    {"label": "Bryce Harper (Total Strikeouts)", "hdp": 0.5, "over": "1.49"},
                    # non-strikeout prop -> excluded
                    {"label": "J.T. Realmuto (Singles)", "hdp": 0.5, "over": "1.98", "under": "1.73"},
                ],
            }
        ],
    },
}


@respx.mock
def test_io_list_events():
    respx.get(f"{IO_BASE}/events").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 123,
                    "home": "Philadelphia Phillies",
                    "away": "Atlanta Braves",
                    "date": "2026-06-15T17:36:00Z",
                    "status": "pending",
                }
            ],
        )
    )
    p = OddsApiIoProvider("KEY", client=httpx.Client(base_url=IO_BASE))
    events = p.list_events()
    assert len(events) == 1
    assert events[0].event_id == "123"  # ints are stringified
    assert events[0].home_team == "Philadelphia Phillies"
    assert events[0].commence_time == "2026-06-15T17:36:00Z"


@respx.mock
def test_io_props_converts_decimal_and_prefers_book():
    respx.get(f"{IO_BASE}/odds").mock(
        return_value=httpx.Response(200, json=IO_PROPS_PAYLOAD)
    )
    p = OddsApiIoProvider("KEY", client=httpx.Client(base_url=IO_BASE))
    by_name = {pl.pitcher_name: pl for pl in p.get_strikeout_props("123")}

    nola = by_name["Aaron Nola"]  # label parenthetical stripped to clean name
    assert nola.bookmaker == "draftkings"  # preferred over fanduel
    assert nola.line == 5.5
    assert nola.over_odds == pytest.approx(100.0)   # decimal 2.00
    assert nola.under_odds == pytest.approx(-125.0)  # decimal 1.80
    # even-money 1.90 both sides -> symmetric American
    assert by_name["Bryce Elder"].over_odds == pytest.approx(-111.111, rel=1e-3)
    # batter "Total Strikeouts" and non-strikeout props are excluded
    assert "Bryce Harper" not in by_name
    assert "J.T. Realmuto" not in by_name


@respx.mock
def test_io_quotes_keeps_all_books():
    respx.get(f"{IO_BASE}/odds").mock(
        return_value=httpx.Response(200, json=IO_PROPS_PAYLOAD)
    )
    p = OddsApiIoProvider("KEY", client=httpx.Client(base_url=IO_BASE))
    quotes = p.get_strikeout_quotes("123")
    nola_books = {q.bookmaker for q in quotes["Aaron Nola"]}
    assert nola_books == {"draftkings", "fanduel"}


@respx.mock
def test_io_props_drops_incomplete_rows():
    payload = {
        "id": 9,
        "bookmakers": {
            "DraftKings": [
                {
                    "name": "Player Props",
                    "odds": [
                        {"label": "No Under (Pitcher Strikeouts)", "hdp": 6.5, "over": "1.9"},  # missing under
                        {"label": "Bad Price (Pitcher Strikeouts)", "hdp": 5.5, "over": "1.00", "under": "1.9"},  # dec<=1
                        {"label": "No Line (Pitcher Strikeouts)", "over": "1.9", "under": "1.9"},  # missing hdp
                        {"label": "No Type Marker", "hdp": 5.5, "over": "1.9", "under": "1.9"},  # no "(...)"
                    ],
                }
            ]
        },
    }
    respx.get(f"{IO_BASE}/odds").mock(return_value=httpx.Response(200, json=payload))
    p = OddsApiIoProvider("KEY", client=httpx.Client(base_url=IO_BASE))
    assert p.get_strikeout_props("9") == []


def test_io_requires_key():
    with pytest.raises(ValueError):
        OddsApiIoProvider("")
