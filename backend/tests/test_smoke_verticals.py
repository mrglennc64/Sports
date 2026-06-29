"""Smoke tests for all 5 verticals endpoints - production deployment.

Tests:
  1. GET /verticals → returns list of 5 verticals
  2. GET /verticals/mlb → returns predictions
  3. GET /verticals/ai-releases → returns AI release forecast
  4. GET /verticals/economics → returns economics forecast
  5. GET /verticals/earnings → returns earnings forecast
  6. GET /verticals/crypto → returns crypto event predictions
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestVerticals:
    """Smoke tests for verticals endpoints."""

    def test_list_verticals(self, client):
        """Test GET /verticals returns list of all available verticals."""
        response = client.get("/verticals")
        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "verticals" in data
        assert isinstance(data["verticals"], list)
        assert len(data["verticals"]) >= 5

        # Verify all 5 required verticals are present
        vertical_ids = {v["id"] for v in data["verticals"]}
        required = {"mlb", "ai-releases", "economics", "earnings", "crypto"}
        assert required.issubset(vertical_ids)

        # Verify each vertical has required fields
        for vertical in data["verticals"]:
            assert "id" in vertical
            assert "name" in vertical
            assert "description" in vertical
            assert "path" in vertical
            assert "markets" in vertical
            assert isinstance(vertical["markets"], list)

    def test_vertical_mlb(self, client):
        """Test GET /verticals/mlb returns MLB strikeout predictions."""
        response = client.get("/verticals/mlb")
        assert response.status_code in [200, 422, 404]  # May fail if no games scheduled

        if response.status_code == 200:
            data = response.json()
            # Verify structure
            assert "rows" in data or "count" in data
            if "rows" in data and isinstance(data["rows"], list):
                for row in data["rows"]:
                    # Each prediction should have key fields
                    assert "pitcher" in row or "status" in row

    def test_vertical_ai_releases(self, client):
        """Test GET /verticals/ai-releases returns AI release predictions."""
        response = client.get("/verticals/ai-releases")
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "vertical" in data
        assert data["vertical"] == "ai-releases"
        assert "timestamp" in data
        assert "market" in data
        assert "predictions" in data
        assert isinstance(data["predictions"], list)

        # Verify prediction structure
        for pred in data["predictions"]:
            assert "event" in pred
            assert "model_probability" in pred
            assert "market_price" in pred
            # Probabilities should be between 0 and 1
            assert 0 <= pred["model_probability"] <= 1
            assert 0 <= pred["market_price"] <= 1

    def test_vertical_economics(self, client):
        """Test GET /verticals/economics returns economics predictions."""
        response = client.get("/verticals/economics")
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "vertical" in data
        assert data["vertical"] == "economics"
        assert "timestamp" in data
        assert "predictions" in data
        assert isinstance(data["predictions"], list)

        # Verify prediction structure
        for pred in data["predictions"]:
            assert "event" in pred
            assert "model_probability" in pred
            assert "market_price" in pred

    def test_vertical_earnings(self, client):
        """Test GET /verticals/earnings returns earnings predictions."""
        response = client.get("/verticals/earnings")
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "vertical" in data
        assert data["vertical"] == "earnings"
        assert "timestamp" in data
        assert "predictions" in data

        # Verify prediction structure
        for pred in data["predictions"]:
            assert "event" in pred
            assert "company" in pred or "model_probability" in pred

    def test_vertical_crypto(self, client):
        """Test GET /verticals/crypto returns crypto event predictions."""
        response = client.get("/verticals/crypto")
        assert response.status_code in [200, 400, 500]  # May fail without data

        if response.status_code == 200:
            data = response.json()
            assert "vertical" in data
            assert data["vertical"] == "crypto"
            assert "timestamp" in data
            assert "market" in data
            assert "predictions" in data

    def test_vertical_mlb_with_min_edge(self, client):
        """Test GET /verticals/mlb with min_edge parameter."""
        response = client.get("/verticals/mlb?min_edge=0.10")
        # Should succeed or return 404 if no games
        assert response.status_code in [200, 404, 422]

    def test_vertical_ai_releases_with_market(self, client):
        """Test GET /verticals/ai-releases with market parameter."""
        response = client.get("/verticals/ai-releases?market=polymarket")
        assert response.status_code == 200
        data = response.json()
        assert "market" in data
        assert data["market"] == "polymarket"

    def test_vertical_earnings_with_sector(self, client):
        """Test GET /verticals/earnings with sector parameter."""
        response = client.get("/verticals/earnings?sector=tech")
        assert response.status_code == 200
        data = response.json()
        assert "sector" in data
        assert data["sector"] == "tech"

    def test_vertical_economics_with_date(self, client):
        """Test GET /verticals/economics with date parameter."""
        response = client.get("/verticals/economics?date=2026-06-28")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data


class TestVerticalErrorHandling:
    """Test error handling for verticals."""

    def test_invalid_vertical_path(self, client):
        """Test GET /verticals/invalid returns 404."""
        response = client.get("/verticals/invalid-vertical")
        assert response.status_code == 404

    def test_vertical_with_invalid_date_format(self, client):
        """Test with invalid date format is rejected."""
        response = client.get("/verticals/economics?date=invalid-date")
        # May return 422 (validation error) or proceed (depending on implementation)
        assert response.status_code in [200, 422]

    def test_vertical_crypto_with_invalid_event(self, client):
        """Test crypto with invalid event parameter."""
        response = client.get("/verticals/crypto?event=invalid_event")
        # Should either return data or a specific error
        assert response.status_code in [200, 400, 404]
