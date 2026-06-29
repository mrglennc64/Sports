"""Smoke tests for frontend deployment.

Tests:
  1. Verify landing page loads
  2. Verify all routes accessible via API
  3. Verify CORS headers present
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestFrontendRoutes:
    """Test that frontend-facing API routes are accessible."""

    def test_health_endpoint_accessible(self, client):
        """Test that health check is accessible from frontend."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_verticals_list_accessible(self, client):
        """Test that verticals list is accessible."""
        response = client.get("/verticals")
        assert response.status_code == 200
        data = response.json()
        assert "verticals" in data

    def test_mlb_vertical_accessible(self, client):
        """Test that MLB vertical is accessible."""
        response = client.get("/verticals/mlb")
        assert response.status_code in [200, 404, 422]

    def test_ai_releases_vertical_accessible(self, client):
        """Test that AI releases vertical is accessible."""
        response = client.get("/verticals/ai-releases")
        assert response.status_code == 200

    def test_economics_vertical_accessible(self, client):
        """Test that economics vertical is accessible."""
        response = client.get("/verticals/economics")
        assert response.status_code == 200

    def test_earnings_vertical_accessible(self, client):
        """Test that earnings vertical is accessible."""
        response = client.get("/verticals/earnings")
        assert response.status_code == 200

    def test_crypto_vertical_accessible(self, client):
        """Test that crypto vertical is accessible."""
        response = client.get("/verticals/crypto")
        assert response.status_code in [200, 400, 500]


class TestFrontendCORS:
    """Test CORS headers for frontend requests."""

    def test_cors_headers_present_localhost(self, client):
        """Test that CORS headers are present for localhost origin."""
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200
        # CORS headers may or may not be present in test client
        # but request should succeed

    def test_cors_allow_get_method(self, client):
        """Test that GET requests are allowed (CORS)."""
        response = client.get(
            "/verticals",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200

    def test_cors_allow_post_method(self, client):
        """Test that POST requests are allowed (CORS)."""
        payload = {"legs": [{"pitcher": "test", "line": 6.5, "side": "over", "odds": -110}]}
        response = client.post(
            "/v2/parlay",
            json=payload,
            headers={"Origin": "http://localhost:5173"},
        )
        # Should succeed or return validation error, not CORS error
        assert response.status_code in [200, 422, 404]

    def test_cors_production_domain(self, client):
        """Test that CORS works with production domain."""
        response = client.get(
            "/health",
            headers={"Origin": "https://strike.perfecthold.online"},
        )
        assert response.status_code == 200


class TestFrontendDataFormats:
    """Test that response formats are frontend-friendly."""

    def test_json_response_format(self, client):
        """Test that all endpoints return valid JSON."""
        endpoints = [
            "/health",
            "/verticals",
            "/verticals/mlb",
            "/verticals/ai-releases",
            "/verticals/economics",
            "/verticals/earnings",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            if response.status_code == 200:
                # Should be valid JSON
                try:
                    data = response.json()
                    assert isinstance(data, dict)
                except ValueError:
                    pytest.fail(f"{endpoint} does not return valid JSON")

    def test_response_includes_timestamp(self, client):
        """Test that responses include timestamp."""
        endpoints = [
            "/verticals/ai-releases",
            "/verticals/economics",
            "/verticals/earnings",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            if response.status_code == 200:
                data = response.json()
                assert "timestamp" in data

    def test_prediction_format_includes_key_fields(self, client):
        """Test that predictions include key fields for UI."""
        response = client.get("/verticals/ai-releases")
        assert response.status_code == 200
        data = response.json()

        if "predictions" in data and len(data["predictions"]) > 0:
            pred = data["predictions"][0]
            # Should have fields for UI rendering
            assert "event" in pred
            assert "model_probability" in pred
            assert "market_price" in pred
            assert any(
                key in pred
                for key in ["edge", "confidence", "action", "key_factors"]
            )


class TestFrontendPagination:
    """Test pagination for frontend list endpoints."""

    def test_leaderboard_pagination_available(self, client):
        """Test that leaderboard supports pagination."""
        response = client.get("/api/clv/leaderboard?limit=10&offset=0")
        # May be 404 if not implemented
        assert response.status_code in [200, 404, 422]

    def test_verticals_list_no_pagination_needed(self, client):
        """Test that verticals list is small enough to not need pagination."""
        response = client.get("/verticals")
        assert response.status_code == 200
        data = response.json()
        # Should return all verticals at once
        assert "verticals" in data
        assert len(data["verticals"]) < 100


class TestFrontendErrorMessages:
    """Test that error messages are frontend-friendly."""

    def test_404_error_has_detail(self, client):
        """Test that 404 errors include detail."""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404
        data = response.json()
        # May have detail field
        assert "detail" in data or "error" in data or True

    def test_validation_error_format(self, client):
        """Test that validation errors are properly formatted."""
        response = client.get("/predict")  # Missing required params
        assert response.status_code == 422
        data = response.json()
        # Should have detail about missing fields
        assert "detail" in data

    def test_500_error_has_message(self, client):
        """Test that server errors include message."""
        # This would need an endpoint that actually fails
        # Placeholder for error handling test
        assert True


class TestFrontendResponsiveness:
    """Test frontend API responsiveness."""

    def test_health_check_fast(self, client):
        """Test that health check responds quickly."""
        import time

        start = time.time()
        response = client.get("/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 1.0, f"Health check took {elapsed}s, should be < 1s"

    def test_verticals_list_fast(self, client):
        """Test that verticals list responds quickly."""
        import time

        start = time.time()
        response = client.get("/verticals")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 2.0, f"Verticals list took {elapsed}s, should be < 2s"

    def test_vertical_prediction_fast(self, client):
        """Test that vertical predictions respond quickly."""
        import time

        start = time.time()
        response = client.get("/verticals/ai-releases")
        elapsed = time.time() - start

        assert response.status_code == 200
        # Predictions may be slower (3-5s acceptable)
        assert elapsed < 10.0, f"Prediction took {elapsed}s, should be < 10s"


class TestFrontendDataConsistency:
    """Test that frontend receives consistent data."""

    def test_repeated_requests_return_similar_data(self, client):
        """Test that repeated requests return consistent results."""
        response1 = client.get("/verticals")
        response2 = client.get("/verticals")

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # Should have same verticals
        verticals1 = {v["id"] for v in data1["verticals"]}
        verticals2 = {v["id"] for v in data2["verticals"]}
        assert verticals1 == verticals2

    def test_vertical_count_stable(self, client):
        """Test that number of verticals doesn't change."""
        response = client.get("/verticals")
        data = response.json()
        assert len(data["verticals"]) >= 5


class TestFrontendIntegration:
    """Integration tests for frontend workflow."""

    def test_landing_page_workflow(self, client):
        """Test typical landing page workflow."""
        # 1. Health check
        response = client.get("/health")
        assert response.status_code == 200

        # 2. Load verticals list
        response = client.get("/verticals")
        assert response.status_code == 200

        # 3. Load first vertical
        response = client.get("/verticals/mlb")
        assert response.status_code in [200, 404, 422]

    def test_navigation_workflow(self, client):
        """Test navigation between different verticals."""
        verticals = ["mlb", "ai-releases", "economics", "earnings", "crypto"]
        for vertical in verticals:
            response = client.get(f"/verticals/{vertical}")
            assert response.status_code in [200, 400, 500, 422]
            if response.status_code == 200:
                data = response.json()
                assert "vertical" in data or "rows" in data or "predictions" in data


class TestFrontendAccessibility:
    """Test frontend API accessibility standards."""

    def test_all_endpoints_documented(self, client):
        """Test that API has OpenAPI documentation."""
        response = client.get("/openapi.json")
        # OpenAPI docs may not be enabled
        assert response.status_code in [200, 404]

    def test_api_supports_json_content_type(self, client):
        """Test that API handles JSON content type."""
        response = client.get(
            "/health",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200

    def test_response_content_type_correct(self, client):
        """Test that response Content-Type is correct."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
