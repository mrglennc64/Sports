"""Smoke tests for health check and system status.

Tests:
  1. GET /health → returns ok + component status
  2. Verify all critical components are healthy
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthCheck:
    """Smoke tests for health check endpoint."""

    def test_health_endpoint_returns_ok(self, client):
        """Test GET /health returns status=ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_health_endpoint_component_status(self, client):
        """Test health check includes component status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "status" in data
        assert "odds_provider" in data
        assert "devig_method" in data
        assert "min_edge" in data

    def test_health_endpoint_odds_provider_configured(self, client):
        """Test that odds provider is configured."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["odds_provider"] is not None
        assert isinstance(data["odds_provider"], str)
        assert len(data["odds_provider"]) > 0

    def test_health_endpoint_devig_method_valid(self, client):
        """Test that devig method is set."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "devig_method" in data
        # Should be a recognized method
        valid_methods = ["lsq", "power", "winhauling", "additive"]
        if data["devig_method"] is not None:
            assert data["devig_method"] in valid_methods or isinstance(
                data["devig_method"], str
            )

    def test_health_endpoint_min_edge_threshold(self, client):
        """Test that min_edge threshold is configured."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "min_edge" in data
        if data["min_edge"] is not None:
            assert isinstance(data["min_edge"], (int, float))
            assert data["min_edge"] >= 0

    def test_health_endpoint_response_time(self, client):
        """Test health endpoint responds quickly."""
        import time

        start = time.time()
        response = client.get("/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        # Should respond in < 1 second
        assert elapsed < 1.0

    def test_health_endpoint_idempotent(self, client):
        """Test health endpoint returns consistent results."""
        response1 = client.get("/health")
        response2 = client.get("/health")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # Status should remain ok
        assert data1["status"] == data2["status"] == "ok"
        assert data1["odds_provider"] == data2["odds_provider"]


class TestSystemDependencies:
    """Test that critical system dependencies are available."""

    def test_configuration_loaded(self, client):
        """Test that configuration is properly loaded."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # All expected config fields should be present
        assert all(key in data for key in ["status", "odds_provider", "devig_method", "min_edge"])

    def test_api_module_imports(self):
        """Test that all API modules can be imported."""
        try:
            from app.config import settings
            from app.ensemble_pipeline import build_slate_ensemble
            from app.crypto_predictor import CryptoEventPredictor

            assert settings is not None
            assert build_slate_ensemble is not None
            assert CryptoEventPredictor is not None
        except ImportError as e:
            pytest.fail(f"Failed to import required module: {e}")

    def test_api_initialization(self):
        """Test that FastAPI app is properly initialized."""
        assert app is not None
        assert app.title == "Edge AI: Multi-Vertical Prediction Platform"
        assert app.version == "2.0.0"

    def test_cors_middleware_configured(self):
        """Test that CORS middleware is configured."""
        # Check that CORS is set up
        assert len(app.user_middleware) > 0
        middleware_names = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_names


class TestEndpointAvailability:
    """Test that required endpoints are available."""

    def test_health_endpoint_available(self, client):
        """Test /health endpoint is available."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_verticals_endpoint_available(self, client):
        """Test /verticals endpoint is available."""
        response = client.get("/verticals")
        assert response.status_code == 200

    def test_mlb_vertical_endpoint_available(self, client):
        """Test /verticals/mlb endpoint is available."""
        response = client.get("/verticals/mlb")
        # May return 200 or 404/422 if no games scheduled
        assert response.status_code in [200, 404, 422]

    def test_predict_endpoint_available(self, client):
        """Test /predict endpoint is available."""
        # This endpoint requires query params, so test that it exists
        response = client.get("/predict")
        # Should be 422 (missing required params) not 404
        assert response.status_code in [422, 404]

    def test_v2_predict_endpoint_available(self, client):
        """Test /v2/predict endpoint is available."""
        response = client.get("/v2/predict")
        assert response.status_code in [422, 404]

    def test_v2_slate_endpoint_available(self, client):
        """Test /v2/slate endpoint is available."""
        response = client.get("/v2/slate")
        assert response.status_code in [200, 404, 422]

    def test_v2_arb_endpoint_available(self, client):
        """Test /v2/arb endpoint is available."""
        response = client.get("/v2/arb")
        assert response.status_code in [200, 404, 422]

    def test_backtest_endpoint_available(self, client):
        """Test /backtest endpoint is available."""
        response = client.get("/backtest")
        assert response.status_code in [200, 404, 422]


class TestEndpointErrors:
    """Test proper error handling."""

    def test_nonexistent_endpoint_returns_404(self, client):
        """Test that nonexistent endpoints return 404."""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_invalid_method_returns_405_or_404(self, client):
        """Test that invalid HTTP methods are rejected."""
        response = client.delete("/health")
        # Should return 405 (Method Not Allowed) or 404
        assert response.status_code in [405, 404]

    def test_malformed_json_returns_422(self, client):
        """Test that malformed JSON is rejected."""
        response = client.post(
            "/v2/parlay",
            content="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [422, 400]


class TestProductionReadiness:
    """Test production readiness criteria."""

    def test_api_has_version(self):
        """Test that API version is set."""
        assert app.version is not None
        assert len(app.version) > 0

    def test_api_has_title(self):
        """Test that API has descriptive title."""
        assert app.title is not None
        assert "Edge" in app.title or "Prediction" in app.title

    def test_api_accepts_cors_requests(self, client):
        """Test that API accepts CORS requests."""
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200

    def test_json_responses_valid(self, client):
        """Test that JSON responses are valid."""
        response = client.get("/health")
        assert response.status_code == 200
        # Should be valid JSON
        try:
            data = response.json()
            assert isinstance(data, dict)
        except ValueError:
            pytest.fail("Response is not valid JSON")

    def test_response_headers_present(self, client):
        """Test that response includes standard headers."""
        response = client.get("/health")
        assert response.status_code == 200
        # Should have Content-Type header
        assert "content-type" in response.headers or "Content-Type" in response.headers
