"""
Integration tests for receipts API.

These tests verify the receipt scanning and resolution endpoints.
"""

import pytest
import base64
from unittest.mock import patch, MagicMock, AsyncMock


class TestReceiptScanEndpoint:
    """Tests for POST /api/receipts/scan"""

    @pytest.mark.integration
    def test_scan_requires_user_id(self, client):
        """Should require user_id parameter."""
        response = client.post(
            "/api/receipts/scan",
            json={
                "image_base64": base64.b64encode(b"fake image").decode(),
                "mime_type": "image/jpeg",
            }
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.integration
    def test_scan_invalid_base64(self, client, test_user_id):
        """Should reject invalid base64 data."""
        response = client.post(
            f"/api/receipts/scan?user_id={test_user_id}",
            json={
                "image_base64": "not-valid-base64!!!",
                "mime_type": "image/jpeg",
            }
        )
        assert response.status_code == 400
        assert "Invalid base64" in response.json()["detail"]

    @pytest.mark.integration
    def test_scan_returns_503_when_ocr_disabled(self, client, test_user_id, image_bytes):
        """Should return 503 when OCR is not configured."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock.return_value.is_enabled = False

            response = client.post(
                f"/api/receipts/scan?user_id={test_user_id}",
                json={
                    "image_base64": base64.b64encode(image_bytes).decode(),
                    "mime_type": "image/jpeg",
                }
            )
            assert response.status_code == 503


class TestReceiptGetEndpoint:
    """Tests for GET /api/receipts/{receipt_id}"""

    @pytest.mark.integration
    def test_get_receipt_not_found(self, client, test_user_id):
        """Should return 404 for non-existent receipt."""
        response = client.get(
            f"/api/receipts/nonexistent-uuid?user_id={test_user_id}"
        )
        assert response.status_code == 404

    @pytest.mark.integration
    def test_get_receipt_requires_user_id(self, client):
        """Should require user_id parameter."""
        response = client.get("/api/receipts/some-uuid")
        assert response.status_code == 422


class TestReceiptUnresolvedEndpoint:
    """Tests for GET /api/receipts/{receipt_id}/unresolved"""

    @pytest.mark.integration
    def test_unresolved_not_found(self, client, test_user_id):
        """Should return 404 for non-existent receipt."""
        response = client.get(
            f"/api/receipts/nonexistent-uuid/unresolved?user_id={test_user_id}"
        )
        assert response.status_code == 404


class TestReceiptBarcodeEndpoint:
    """Tests for POST /api/receipts/{receipt_id}/items/{index}/scan-barcode"""

    @pytest.mark.integration
    def test_barcode_scan_requires_params(self, client):
        """Should require all parameters."""
        response = client.post(
            "/api/receipts/some-uuid/items/0/scan-barcode"
        )
        assert response.status_code == 422

    @pytest.mark.integration
    def test_barcode_scan_receipt_not_found(self, client, test_user_id):
        """Should return 404 for non-existent receipt."""
        response = client.post(
            f"/api/receipts/nonexistent/items/0/scan-barcode?barcode=012345678905&user_id={test_user_id}"
        )
        assert response.status_code == 404


class TestReceiptManualResolveEndpoint:
    """Tests for POST /api/receipts/{receipt_id}/items/{index}/resolve-manual"""

    @pytest.mark.integration
    def test_manual_resolve_receipt_not_found(self, client, test_user_id):
        """Should return 404 for non-existent receipt."""
        response = client.post(
            f"/api/receipts/nonexistent/items/0/resolve-manual?user_id={test_user_id}",
            json={"food_item_id": "some-uuid"}
        )
        assert response.status_code == 404

    @pytest.mark.integration
    def test_manual_resolve_requires_action(self, client, test_user_id):
        """Should require at least one action (food_item_id, create_new, or skip)."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock_receipt = MagicMock()
            mock_receipt.line_items = [MagicMock()]
            mock.return_value.get_receipt = AsyncMock(return_value=mock_receipt)

            response = client.post(
                f"/api/receipts/some-uuid/items/0/resolve-manual?user_id={test_user_id}",
                json={}  # No action specified
            )
            assert response.status_code == 400
            assert "Must provide" in response.json()["detail"]


class TestReceiptHistoryEndpoint:
    """Tests for GET /api/receipts/"""

    @pytest.mark.integration
    def test_history_requires_user_id(self, client):
        """Should require user_id parameter."""
        response = client.get("/api/receipts/")
        assert response.status_code == 422

    @pytest.mark.integration
    def test_history_pagination(self, client, test_user_id):
        """Should support limit and offset parameters."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock.return_value.get_receipt_history = AsyncMock(return_value=[])

            response = client.get(
                f"/api/receipts/?user_id={test_user_id}&limit=10&offset=0"
            )
            assert response.status_code == 200

    @pytest.mark.integration
    def test_history_limit_validation(self, client, test_user_id):
        """Should validate limit range (1-100)."""
        response = client.get(
            f"/api/receipts/?user_id={test_user_id}&limit=200"
        )
        assert response.status_code == 422  # Exceeds max


class TestReceiptStatsEndpoint:
    """Tests for GET /api/receipts/stats/summary"""

    @pytest.mark.integration
    def test_stats_requires_user_id(self, client):
        """Should require user_id parameter."""
        response = client.get("/api/receipts/stats/summary")
        assert response.status_code == 422

    @pytest.mark.integration
    def test_stats_returns_structure(self, client, test_user_id):
        """Should return expected stats structure."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock.return_value.get_stats = AsyncMock(return_value=MagicMock(
                total_receipts=5,
                total_items_scanned=50,
                total_items_matched=40,
                match_rate=0.8,
                total_spent=100.00,
                receipts_this_month=2,
            ))

            response = client.get(
                f"/api/receipts/stats/summary?user_id={test_user_id}"
            )
            assert response.status_code == 200
