"""Tests for the async ensemble pipeline and the v2 FastAPI routes."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main
from app.data.client import StatsApiClient
from app.ensemble_pipeline import predict_pitcher_ensemble

BASE = "https://statsapi.mlb.com"


def _run(coro):
    return asyncio.run(coro)


def _client() -> StatsApiClient:
    return StatsApiClient(client=httpx.AsyncClient(base_url=BASE))


def _schedule():
    return {
        "dates": [{"games": [{
            "gamePk": 777,
            "venue": {"name": "Fenway Park"},
            "teams": {
                "away": {
                    "team": {"id": 147, "name": "New York Yankees"},
                    "probablePitcher": {"id": 1, "fullName": "Gerrit Cole", "pitchHand": {"code": "R"}},
                },
                "home": {
                    "team": {"id": 111, "name": "Boston Red Sox"},
                    "probablePitcher": {"id": 2, "fullName": "Home Ace", "pitchHand": {"code": "L"}},
                },
            },
        }]}]
    }


def _gamelog(pid):
    return {"people": [{"id": pid, "stats": [{"splits": [
        {"date": "2025-05-20", "stat": {"strikeOuts": 7, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-05-26", "stat": {"strikeOuts": 8, "gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-06-01", "stat": {"strikeOuts": 9, "gamesStarted": 1, "inningsPitched": "7.0"}},
    ]}]}]}


def _mock_statsapi():
    """One host router answering every MLB Stats endpoint the assembler hits."""
    splits = {"stats": [{"splits": [
        {"split": {"code": "vl"}, "stat": {"strikeOuts": 400, "plateAppearances": 1697}},
        {"split": {"code": "vr"}, "stat": {"strikeOuts": 1063, "plateAppearances": 4538}},
    ]}]}
    window = {"stats": [{"splits": [{"stat": {"strikeOuts": 100, "plateAppearances": 400}}]}]}

    def router(request):
        path = request.url.path
        params = request.url.params
        if path == "/api/v1/schedule":
            if params.get("gamePk"):
                return httpx.Response(200, json={"dates": [{"games": [{
                    "gamePk": 777, "lineups": {"homePlayers": [], "awayPlayers": []}}]}]})
            return httpx.Response(200, json=_schedule())
        if path.endswith("/stats") and "/people/" in path:
            return httpx.Response(200, json={"stats": [{"splits": [
                {"stat": {"inningsPitched": "120.0", "gamesStarted": 20}}]}]})
        if "/people/" in path:
            pid = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=_gamelog(pid))
        if "/teams/" in path:
            if params.get("stats") == "statSplits":
                return httpx.Response(200, json=splits)
            return httpx.Response(200, json=window)
        return httpx.Response(404, json={})

    respx.route(host="statsapi.mlb.com").mock(side_effect=router)


# --------------------------------------------------------------------------- #
# Pipeline integration
# --------------------------------------------------------------------------- #
@respx.mock
def test_predict_pitcher_ensemble_with_odds():
    _mock_statsapi()
    out = _run(predict_pitcher_ensemble(
        "Gerrit Cole", line=6.5, date="2025-06-07",
        over_odds=-110, under_odds=-110, client=_client(),
    ))
    assert out["pitcher"] == "Gerrit Cole"
    assert out["expected_ks"] > 0
    assert out["opponent"] == "Boston Red Sox"
    assert out["venue"] == "Fenway Park"
    # Odds supplied -> the bridge produced an edge + verdict.
    assert "edge" in out
    assert out["recommendation"] in {"Strong Play", "Lean", "No Bet", "Pass"}
    # All seven ensemble lenses are present in the breakdown.
    assert len(out["components"]) == 10


@respx.mock
def test_predict_pitcher_ensemble_without_odds_has_projection_only():
    _mock_statsapi()
    out = _run(predict_pitcher_ensemble(
        "Gerrit Cole", line=6.5, date="2025-06-07", client=_client(),
    ))
    assert out["expected_ks"] > 0
    assert "edge" not in out


@respx.mock
def test_predict_pitcher_ensemble_unknown_pitcher_raises():
    _mock_statsapi()
    with pytest.raises(LookupError):
        _run(predict_pitcher_ensemble(
            "Nobody Here", line=6.5, date="2025-06-07", client=_client(),
        ))


# --------------------------------------------------------------------------- #
# Route wiring (no network: the pipeline functions are stubbed)
# --------------------------------------------------------------------------- #
def test_v2_predict_route_returns_pipeline_result(monkeypatch):
    async def fake(pitcher, line, date, over_odds=None, under_odds=None):
        return {"pitcher": pitcher, "line": line, "expected_ks": 7.2, "date": date}

    monkeypatch.setattr(main, "predict_pitcher_ensemble", fake)
    client = TestClient(main.app)
    r = client.get("/v2/predict", params={"pitcher": "Cole", "line": 6.5, "date": "2025-06-07"})
    assert r.status_code == 200
    body = r.json()
    assert body["expected_ks"] == 7.2
    assert body["pitcher"] == "Cole"


def test_v2_predict_route_404_on_lookup_error(monkeypatch):
    async def fake(**kwargs):
        raise LookupError("not starting")

    monkeypatch.setattr(main, "predict_pitcher_ensemble", fake)
    client = TestClient(main.app)
    r = client.get("/v2/predict", params={"pitcher": "Ghost", "line": 6.5})
    assert r.status_code == 404
    assert "not starting" in r.json()["detail"]


def test_v2_slate_route_applies_min_edge_filter(monkeypatch):
    async def fake(date, **kwargs):
        return {
            "date": date,
            "count": 3,
            "evaluated": 2,
            "bets": 1,
            "rows": [
                {"pitcher": "A", "status": "ok", "edge": 0.10},
                {"pitcher": "B", "status": "ok", "edge": 0.01},
                {"pitcher": "C", "status": "no_prop"},
            ],
        }

    monkeypatch.setattr(main, "build_slate_ensemble", fake)
    client = TestClient(main.app)
    r = client.get("/v2/slate", params={"date": "2025-06-07", "min_edge": 0.05})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert [row["pitcher"] for row in body["rows"]] == ["A"]
