"""
Unit tests for health check service.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from app.services.healthcheck import (
    HealthChecker,
    HealthStatus,
    CheckResult,
    HealthReport,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    @pytest.mark.unit
    def test_check_result_defaults(self):
        """Should have sensible defaults."""
        result = CheckResult(name="test", status=HealthStatus.HEALTHY)
        assert result.message == ""
        assert result.latency_ms == 0
        assert result.details == {}
        assert isinstance(result.timestamp, datetime)

    @pytest.mark.unit
    def test_check_result_with_details(self):
        """Should store details."""
        result = CheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
            message="All good",
            latency_ms=50.5,
            details={"key": "value"},
        )
        assert result.details["key"] == "value"


class TestHealthReport:
    """Tests for HealthReport dataclass."""

    @pytest.mark.unit
    def test_healthy_count(self):
        """Should count healthy checks."""
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[
                CheckResult(name="a", status=HealthStatus.HEALTHY),
                CheckResult(name="b", status=HealthStatus.HEALTHY),
                CheckResult(name="c", status=HealthStatus.UNHEALTHY),
            ]
        )
        assert report.healthy_count == 2
        assert report.total_count == 3

    @pytest.mark.unit
    def test_to_dict(self):
        """Should convert to dictionary."""
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[
                CheckResult(name="test", status=HealthStatus.HEALTHY, message="OK"),
            ]
        )
        data = report.to_dict()

        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "checks" in data
        assert len(data["checks"]) == 1
        assert data["checks"][0]["name"] == "test"


class TestHealthChecker:
    """Tests for HealthChecker service."""

    @pytest.fixture
    def checker(self):
        return HealthChecker()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_api(self, checker):
        """API check should always pass (we're running)."""
        result = await checker.check_api()
        assert result.status == HealthStatus.HEALTHY
        assert result.name == "api"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_supabase_success(self, checker):
        """Should report healthy when Supabase connects."""
        with patch('app.services.supabase.get_supabase_client') as mock:
            mock.return_value.table.return_value.select.return_value.limit.return_value.execute.return_value.data = []

            result = await checker.check_supabase()

            assert result.status == HealthStatus.HEALTHY
            assert result.name == "supabase"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_supabase_failure(self, checker):
        """Should report unhealthy when Supabase fails."""
        with patch('app.services.supabase.get_supabase_client') as mock:
            mock.side_effect = Exception("Connection refused")

            result = await checker.check_supabase()

            assert result.status == HealthStatus.UNHEALTHY
            assert "Connection refused" in result.message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_barcode_cache_exists(self, checker, tmp_path):
        """Should report healthy when cache exists."""
        cache_file = tmp_path / "barcode_cache.db"
        cache_file.write_bytes(b"fake database content" * 1000)

        with patch('app.config.get_settings') as mock:
            mock.return_value.data_dir = str(tmp_path)

            result = await checker.check_barcode_cache()

            assert result.status == HealthStatus.HEALTHY
            assert "size_mb" in result.details

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_barcode_cache_missing(self, checker, tmp_path):
        """Should report degraded when cache doesn't exist."""
        with patch('app.config.get_settings') as mock:
            mock.return_value.data_dir = str(tmp_path)

            result = await checker.check_barcode_cache()

            assert result.status == HealthStatus.DEGRADED
            assert "not initialized" in result.message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_document_ai_enabled(self, checker):
        """Should report healthy when Document AI is configured."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock.return_value.is_enabled = True

            result = await checker.check_document_ai()

            assert result.status == HealthStatus.HEALTHY
            assert result.details["enabled"] == True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_document_ai_disabled(self, checker):
        """Should report degraded when Document AI is not configured."""
        with patch('app.services.receipts.get_receipt_service') as mock:
            mock.return_value.is_enabled = False

            result = await checker.check_document_ai()

            assert result.status == HealthStatus.DEGRADED
            assert result.details["enabled"] == False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_all_checks(self, checker):
        """Should run all checks and return report."""
        with patch.object(checker, 'check_api', new_callable=AsyncMock) as mock_api, \
             patch.object(checker, 'check_supabase', new_callable=AsyncMock) as mock_db, \
             patch.object(checker, 'check_barcode_cache', new_callable=AsyncMock) as mock_bc, \
             patch.object(checker, 'check_usda_cache', new_callable=AsyncMock) as mock_usda, \
             patch.object(checker, 'check_open_food_facts', new_callable=AsyncMock) as mock_off, \
             patch.object(checker, 'check_document_ai', new_callable=AsyncMock) as mock_dai, \
             patch.object(checker, 'check_tesseract', new_callable=AsyncMock) as mock_tess:

            mock_api.return_value = CheckResult(name="api", status=HealthStatus.HEALTHY)
            mock_db.return_value = CheckResult(name="supabase", status=HealthStatus.HEALTHY)
            mock_bc.return_value = CheckResult(name="barcode_cache", status=HealthStatus.HEALTHY)
            mock_usda.return_value = CheckResult(name="usda_cache", status=HealthStatus.HEALTHY)
            mock_off.return_value = CheckResult(name="open_food_facts", status=HealthStatus.HEALTHY)
            mock_dai.return_value = CheckResult(name="document_ai", status=HealthStatus.DEGRADED)
            mock_tess.return_value = CheckResult(name="tesseract", status=HealthStatus.DEGRADED)

            report = await checker.run_all_checks()

            assert report.total_count == 7
            assert report.healthy_count == 5
            # Overall should be degraded because some checks are degraded
            assert report.status == HealthStatus.DEGRADED

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_all_checks_all_healthy(self, checker):
        """Should report healthy when all checks pass."""
        with patch.object(checker, 'check_api', new_callable=AsyncMock) as mock_api, \
             patch.object(checker, 'check_supabase', new_callable=AsyncMock) as mock_db, \
             patch.object(checker, 'check_barcode_cache', new_callable=AsyncMock) as mock_bc, \
             patch.object(checker, 'check_usda_cache', new_callable=AsyncMock) as mock_usda, \
             patch.object(checker, 'check_open_food_facts', new_callable=AsyncMock) as mock_off, \
             patch.object(checker, 'check_document_ai', new_callable=AsyncMock) as mock_dai, \
             patch.object(checker, 'check_tesseract', new_callable=AsyncMock) as mock_tess:

            for mock in [mock_api, mock_db, mock_bc, mock_usda, mock_off, mock_dai, mock_tess]:
                mock.return_value = CheckResult(name="test", status=HealthStatus.HEALTHY)

            report = await checker.run_all_checks()

            assert report.status == HealthStatus.HEALTHY
