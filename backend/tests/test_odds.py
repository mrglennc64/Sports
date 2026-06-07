import httpx
import pytest
import respx

from app.data.names import names_match, normalize_name
from app.data.odds import TheOddsApiProvider, get_provider, UnconfiguredProvider

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
    assert isinstance(get_provider("oddsapiio", "", "uuid"), UnconfiguredProvider)
    with pytest.raises(ValueError):
        get_provider("nope", "", "")


def test_theoddsapi_requires_key():
    with pytest.raises(ValueError):
        TheOddsApiProvider("")
