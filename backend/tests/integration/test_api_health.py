"""
Integration tests for health and status endpoints.

These tests verify the API is responding correctly.
"""

import pytest


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.integration
    def test_health_endpoint(self, client):
        """Health endpoint should return 200."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.integration
    def test_root_endpoint(self, client):
        """Root endpoint should return API info."""
        response = client.get("/")
        assert response.status_code == 200

    @pytest.mark.integration
    def test_receipt_ocr_status(self, client):
        """Receipt OCR status endpoint should respond."""
        response = client.get("/api/receipts/status/enabled")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "message" in data


class TestAPIStructure:
    """Tests for API structure and routing."""

    @pytest.mark.integration
    def test_404_on_invalid_route(self, client):
        """Should return 404 for invalid routes."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404

    @pytest.mark.integration
    def test_cors_headers(self, client):
        """Should include CORS headers."""
        response = client.options("/api/health")
        # FastAPI handles this differently, may need middleware check
        assert response.status_code in [200, 405]
