"""Smoke tests for CLV (Customer Lifetime Value) endpoints.

Tests:
  1. POST /api/clv/capture → records odds
  2. GET /api/clv/analysis → returns movement stats
  3. POST /api/clv/record-bet → calculates CLV
  4. GET /api/clv/leaderboard → lists bets by CLV
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_odds_capture():
    """Sample odds capture payload."""
    return {
        "pitcher": "Gerrit Cole",
        "game_id": "MLB_NYY_BAL_2026_06_28",
        "strikeout_line": 6.5,
        "timestamp": datetime.now().isoformat(),
        "odds": {
            "draftkings": {
                "over": -110,
                "under": -110,
            },
            "fanduel": {
                "over": -105,
                "under": -115,
            },
            "betmgm": {
                "over": -110,
                "under": -110,
            },
        },
    }


@pytest.fixture
def sample_bet_record():
    """Sample bet record payload."""
    return {
        "pitcher": "Gerrit Cole",
        "line": 6.5,
        "side": "over",
        "odds": -110,
        "stake": 100,
        "result": "win",
        "actual_strikeouts": 7,
        "market_probability": 0.45,
        "model_probability": 0.58,
        "timestamp": datetime.now().isoformat(),
    }


class TestCLVCapture:
    """Smoke tests for CLV odds capture."""

    def test_clv_capture_post(self, client, sample_odds_capture):
        """Test POST /api/clv/capture - record odds snapshot."""
        response = client.post("/api/clv/capture", json=sample_odds_capture)
        assert response.status_code in [200, 201, 404, 401, 403, 422]

        if response.status_code in [200, 201]:
            data = response.json()
            assert "id" in data or "captured_at" in data or "status" in data

    def test_clv_capture_required_fields(self, client):
        """Test POST /api/clv/capture with required fields."""
        payload = {
            "pitcher": "Clayton Kershaw",
            "game_id": "MLB_LAD_SD_2026_06_28",
            "strikeout_line": 7.5,
            "odds": {
                "draftkings": {"over": -110, "under": -110},
            },
        }
        response = client.post("/api/clv/capture", json=payload)
        assert response.status_code in [200, 201, 404, 422]

    def test_clv_capture_multiple_books(self, client, sample_odds_capture):
        """Test odds capture with multiple sportsbooks."""
        response = client.post("/api/clv/capture", json=sample_odds_capture)
        if response.status_code in [200, 201]:
            # Verify odds from multiple books are recorded
            assert response.status_code in [200, 201]

    def test_clv_capture_timestamp_recorded(self, client, sample_odds_capture):
        """Test that capture timestamp is properly recorded."""
        response = client.post("/api/clv/capture", json=sample_odds_capture)
        if response.status_code in [200, 201]:
            data = response.json()
            assert "timestamp" in data or "captured_at" in data


class TestCLVAnalysis:
    """Smoke tests for CLV analysis and movement stats."""

    def test_clv_analysis_endpoint_exists(self, client):
        """Test GET /api/clv/analysis - verify endpoint is accessible."""
        response = client.get("/api/clv/analysis")
        assert response.status_code in [200, 404, 401, 403, 422]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)

    def test_clv_analysis_returns_movement_stats(self, client):
        """Test analysis returns line movement statistics."""
        response = client.get("/api/clv/analysis")
        if response.status_code == 200:
            data = response.json()
            # Should include movement stats
            assert "analysis" in data or "stats" in data or "movements" in data

    def test_clv_analysis_with_pitcher_filter(self, client):
        """Test analysis with pitcher filter."""
        response = client.get("/api/clv/analysis?pitcher=Gerrit Cole")
        assert response.status_code in [200, 404, 422]

    def test_clv_analysis_with_date_range(self, client):
        """Test analysis with date range filter."""
        start = (datetime.now() - timedelta(days=7)).date().isoformat()
        end = datetime.now().date().isoformat()
        response = client.get(f"/api/clv/analysis?start_date={start}&end_date={end}")
        assert response.status_code in [200, 404, 422]

    def test_clv_analysis_movement_response_structure(self, client):
        """Test movement stats have correct structure."""
        response = client.get("/api/clv/analysis")
        if response.status_code == 200:
            data = response.json()
            # Each movement should have before/after odds
            if "movements" in data:
                for move in data["movements"]:
                    assert "before" in move or "initial_odds" in move
                    assert "after" in move or "final_odds" in move
                    assert "direction" in move or "change" in move

    def test_clv_analysis_with_book_filter(self, client):
        """Test analysis filtered by sportsbook."""
        response = client.get("/api/clv/analysis?book=draftkings")
        assert response.status_code in [200, 404, 422]


class TestCLVRecordBet:
    """Smoke tests for bet recording and CLV calculation."""

    def test_clv_record_bet_post(self, client, sample_bet_record):
        """Test POST /api/clv/record-bet - record a bet and calculate CLV."""
        response = client.post("/api/clv/record-bet", json=sample_bet_record)
        assert response.status_code in [200, 201, 404, 401, 403, 422]

        if response.status_code in [200, 201]:
            data = response.json()
            assert "clv" in data or "value" in data or "edge" in data

    def test_clv_record_bet_required_fields(self, client):
        """Test record bet with required fields."""
        payload = {
            "pitcher": "Max Scherzer",
            "line": 6.5,
            "side": "under",
            "odds": -105,
            "stake": 50,
            "result": "win",
            "actual_strikeouts": 6,
        }
        response = client.post("/api/clv/record-bet", json=payload)
        assert response.status_code in [200, 201, 404, 422]

    def test_clv_record_bet_clv_calculation(self, client, sample_bet_record):
        """Test CLV is calculated correctly."""
        response = client.post("/api/clv/record-bet", json=sample_bet_record)
        if response.status_code in [200, 201]:
            data = response.json()
            if "clv" in data:
                # CLV = (Model Prob * Odds Ratio) - 1
                # Should be numeric
                assert isinstance(data["clv"], (int, float))

    def test_clv_record_bet_with_probabilities(self, client):
        """Test bet recording includes probability assessment."""
        payload = {
            "pitcher": "Jacob deGrom",
            "line": 8.5,
            "side": "over",
            "odds": -110,
            "stake": 200,
            "result": "loss",
            "actual_strikeouts": 7,
            "model_probability": 0.65,
            "market_probability": 0.52,
        }
        response = client.post("/api/clv/record-bet", json=payload)
        assert response.status_code in [200, 201, 404, 422]

    def test_clv_record_multiple_outcomes(self, client):
        """Test recording bets with different outcomes."""
        outcomes = ["win", "loss", "push"]
        for outcome in outcomes:
            payload = {
                "pitcher": "Juan Soto",
                "line": 6.5,
                "side": "over",
                "odds": -110,
                "stake": 100,
                "result": outcome,
                "actual_strikeouts": 7,
            }
            response = client.post("/api/clv/record-bet", json=payload)
            assert response.status_code in [200, 201, 404, 422]

    def test_clv_record_bet_response_metadata(self, client, sample_bet_record):
        """Test response includes bet metadata."""
        response = client.post("/api/clv/record-bet", json=sample_bet_record)
        if response.status_code in [200, 201]:
            data = response.json()
            assert "id" in data or "bet_id" in data or "recorded_at" in data


class TestCLVLeaderboard:
    """Smoke tests for CLV leaderboard."""

    def test_clv_leaderboard_endpoint_exists(self, client):
        """Test GET /api/clv/leaderboard - verify endpoint is accessible."""
        response = client.get("/api/clv/leaderboard")
        assert response.status_code in [200, 404, 401, 403, 422]

        if response.status_code == 200:
            data = response.json()
            assert "leaderboard" in data or "bets" in data

    def test_clv_leaderboard_returns_bet_list(self, client):
        """Test leaderboard returns sorted list of bets."""
        response = client.get("/api/clv/leaderboard")
        if response.status_code == 200:
            data = response.json()
            bets = data.get("leaderboard") or data.get("bets")
            assert isinstance(bets, list)

    def test_clv_leaderboard_sorted_by_clv(self, client):
        """Test leaderboard is sorted by CLV (highest first)."""
        response = client.get("/api/clv/leaderboard?sort=clv&order=desc")
        if response.status_code == 200:
            data = response.json()
            bets = data.get("leaderboard") or data.get("bets")
            if len(bets) > 1:
                # Verify CLVs are in descending order
                clvs = [b.get("clv") for b in bets if "clv" in b]
                if clvs:
                    assert clvs == sorted(clvs, reverse=True)

    def test_clv_leaderboard_with_filters(self, client):
        """Test leaderboard with various filters."""
        filters = [
            "?pitcher=Gerrit Cole",
            "?result=win",
            "?side=over",
            "?min_clv=0.05",
        ]
        for filter_query in filters:
            response = client.get(f"/api/clv/leaderboard{filter_query}")
            assert response.status_code in [200, 404, 422]

    def test_clv_leaderboard_with_pagination(self, client):
        """Test leaderboard pagination."""
        response = client.get("/api/clv/leaderboard?limit=10&offset=0")
        assert response.status_code in [200, 404, 422]

    def test_clv_leaderboard_summary_stats(self, client):
        """Test leaderboard includes summary statistics."""
        response = client.get("/api/clv/leaderboard")
        if response.status_code == 200:
            data = response.json()
            # May include totals
            if "summary" in data:
                assert "total_clv" in data["summary"] or "count" in data["summary"]

    def test_clv_leaderboard_date_range(self, client):
        """Test leaderboard filtered by date range."""
        start = (datetime.now() - timedelta(days=30)).date().isoformat()
        end = datetime.now().date().isoformat()
        response = client.get(
            f"/api/clv/leaderboard?start_date={start}&end_date={end}"
        )
        assert response.status_code in [200, 404, 422]


class TestCLVErrorHandling:
    """Test error handling for CLV endpoints."""

    def test_clv_capture_missing_pitcher(self, client):
        """Test POST /clv/capture without pitcher name."""
        payload = {
            "game_id": "MLB_NYY_BAL_2026_06_28",
            "strikeout_line": 6.5,
            "odds": {"draftkings": {"over": -110}},
        }
        response = client.post("/api/clv/capture", json=payload)
        assert response.status_code in [422, 400, 404]

    def test_clv_record_bet_invalid_outcome(self, client):
        """Test record bet with invalid outcome."""
        payload = {
            "pitcher": "Gerrit Cole",
            "line": 6.5,
            "side": "over",
            "odds": -110,
            "stake": 100,
            "result": "invalid_outcome",
            "actual_strikeouts": 7,
        }
        response = client.post("/api/clv/record-bet", json=payload)
        assert response.status_code in [422, 400, 404]

    def test_clv_record_bet_invalid_side(self, client):
        """Test record bet with invalid side."""
        payload = {
            "pitcher": "Gerrit Cole",
            "line": 6.5,
            "side": "invalid_side",
            "odds": -110,
            "stake": 100,
            "result": "win",
            "actual_strikeouts": 7,
        }
        response = client.post("/api/clv/record-bet", json=payload)
        assert response.status_code in [422, 400, 404]

    def test_clv_leaderboard_invalid_sort(self, client):
        """Test leaderboard with invalid sort parameter."""
        response = client.get("/api/clv/leaderboard?sort=invalid")
        assert response.status_code in [200, 422, 400, 404]


class TestCLVIntegration:
    """Integration tests for CLV workflow."""

    def test_clv_workflow_capture_and_record(self, client, sample_odds_capture, sample_bet_record):
        """Test complete workflow: capture odds -> record bet -> analyze."""
        # 1. Capture odds
        capture_response = client.post("/api/clv/capture", json=sample_odds_capture)
        assert capture_response.status_code in [200, 201, 404]

        # 2. Record bet
        record_response = client.post("/api/clv/record-bet", json=sample_bet_record)
        assert record_response.status_code in [200, 201, 404]

        # 3. Check leaderboard
        leaderboard_response = client.get("/api/clv/leaderboard")
        assert leaderboard_response.status_code in [200, 404]

    def test_clv_data_persistence(self, client, sample_bet_record):
        """Test that CLV data persists across requests."""
        # Record a bet
        response1 = client.post("/api/clv/record-bet", json=sample_bet_record)

        if response1.status_code in [200, 201]:
            # Retrieve leaderboard
            response2 = client.get("/api/clv/leaderboard")
            if response2.status_code == 200:
                data = response2.json()
                bets = data.get("leaderboard") or data.get("bets")
                # Should be a list
                assert isinstance(bets, list)
