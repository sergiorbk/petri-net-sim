"""
Tests for health check endpoints.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from main import app
from src.core.config import settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200(self, client: TestClient):
        """Test that health endpoint returns 200 OK."""
        response = client.get("/health")

        assert response.status_code == 200

    def test_health_response_structure(self, client: TestClient):
        """Test that health response has correct structure."""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert "environment" in data

    def test_health_version_matches_app_version(self, client: TestClient):
        """The version field must echo settings.APP_VERSION, not a stale
        hardcoded field default (it used to always read '0.1.0')."""
        response = client.get("/health")
        data = response.json()

        assert data["version"] == settings.APP_VERSION

    def test_health_status_is_healthy(self, client: TestClient):
        """Test that health status is healthy."""
        response = client.get("/health")
        data = response.json()

        assert data["status"] == "healthy"

    def test_health_uptime_is_positive(self, client: TestClient):
        """Test that uptime is a positive number."""
        response = client.get("/health")
        data = response.json()

        assert data["uptime_seconds"] >= 0

    def test_health_timestamp_format(self, client: TestClient):
        """Test that timestamp is in ISO format."""
        response = client.get("/health")
        data = response.json()

        # Should be parseable as ISO datetime
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        assert isinstance(timestamp, datetime)


class TestLivenessProbe:
    """Tests for /health/live endpoint."""

    def test_liveness_returns_200(self, client: TestClient):
        """Test that liveness probe returns 200 OK."""
        response = client.get("/health/live")

        assert response.status_code == 200

    def test_liveness_response(self, client: TestClient):
        """Test that liveness probe returns alive status."""
        response = client.get("/health/live")
        data = response.json()

        assert data["status"] == "alive"


class TestReadinessProbe:
    """Tests for /health/ready endpoint."""

    def test_readiness_returns_200(self, client: TestClient):
        """Test that readiness probe returns 200 OK."""
        response = client.get("/health/ready")

        assert response.status_code == 200

    def test_readiness_response_structure(self, client: TestClient):
        """Test that readiness response has correct structure."""
        response = client.get("/health/ready")
        data = response.json()

        assert "status" in data
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert "environment" in data
        assert "components" in data

    def test_readiness_version_matches_app_version(self, client: TestClient):
        """Same disconnect fix as /health, checked on the detailed probe too."""
        response = client.get("/health/ready")
        data = response.json()

        assert data["version"] == settings.APP_VERSION

    def test_readiness_has_components(self, client: TestClient):
        """Test that readiness check includes component statuses."""
        response = client.get("/health/ready")
        data = response.json()

        components = data["components"]
        assert "logger" in components
        assert "config" in components

    def test_readiness_component_structure(self, client: TestClient):
        """Test that each component has status and message."""
        response = client.get("/health/ready")
        data = response.json()

        for component_name, component_data in data["components"].items():
            assert "status" in component_data
            assert "message" in component_data
            assert component_data["status"] in ["healthy", "degraded", "unhealthy"]

    def test_readiness_logger_component(self, client: TestClient):
        """Test that logger component is healthy."""
        response = client.get("/health/ready")
        data = response.json()

        logger_status = data["components"]["logger"]
        assert logger_status["status"] == "healthy"

    def test_readiness_config_component(self, client: TestClient):
        """Test that config component is healthy."""
        response = client.get("/health/ready")
        data = response.json()

        config_status = data["components"]["config"]
        assert config_status["status"] == "healthy"


class TestStartupProbe:
    """Tests for /health/startup endpoint."""

    def test_startup_returns_200(self, client: TestClient):
        """Test that startup probe returns 200 OK."""
        response = client.get("/health/startup")

        assert response.status_code == 200

    def test_startup_response(self, client: TestClient):
        """Test that startup probe returns started status."""
        response = client.get("/health/startup")
        data = response.json()

        assert data["status"] == "started"


class TestHealthIntegration:
    """Integration tests for health endpoints."""

    def test_all_health_endpoints_accessible(self, client: TestClient):
        """Test that all health endpoints are accessible."""
        endpoints = [
            "/health",
            "/health/live",
            "/health/ready",
            "/health/startup",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, f"Endpoint {endpoint} failed"

    def test_health_endpoints_return_json(self, client: TestClient):
        """Test that all health endpoints return JSON."""
        endpoints = [
            "/health",
            "/health/live",
            "/health/ready",
            "/health/startup",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.headers["content-type"] == "application/json"

    def test_multiple_health_checks(self, client: TestClient):
        """Test that multiple health checks work consistently."""
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"

    def test_health_check_performance(self, client: TestClient):
        """Test that health check is fast."""
        import time

        start = time.time()
        response = client.get("/health")
        duration = time.time() - start

        assert response.status_code == 200
        # Health check should be fast (< 100ms)
        assert duration < 0.1
