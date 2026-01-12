"""
Comprehensive health check system.

Checks:
- API responsiveness
- Database connectivity (Supabase)
- External services (Open Food Facts, Document AI)
- Cache systems (SQLite caches)
- Background services
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthReport:
    """Complete health report for the system."""
    status: HealthStatus
    checks: list[CheckResult]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    version: str = "2.4.0"

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self.checks if c.status == HealthStatus.HEALTHY)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "summary": f"{self.healthy_count}/{self.total_count} checks passing",
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": round(c.latency_ms, 2),
                    "details": c.details,
                }
                for c in self.checks
            ]
        }


class HealthChecker:
    """Runs health checks against all system components."""

    async def run_all_checks(self) -> HealthReport:
        """Run all health checks and return report."""
        checks = await asyncio.gather(
            self.check_api(),
            self.check_supabase(),
            self.check_barcode_cache(),
            self.check_usda_cache(),
            self.check_open_food_facts(),
            self.check_document_ai(),
            self.check_tesseract(),
            return_exceptions=True,
        )

        # Convert exceptions to failed checks
        results = []
        for check in checks:
            if isinstance(check, Exception):
                results.append(CheckResult(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=str(check),
                ))
            else:
                results.append(check)

        # Determine overall status
        if all(c.status == HealthStatus.HEALTHY for c in results):
            overall = HealthStatus.HEALTHY
        elif any(c.status == HealthStatus.UNHEALTHY for c in results):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.DEGRADED

        return HealthReport(status=overall, checks=results)

    async def check_api(self) -> CheckResult:
        """Check API is responsive."""
        start = time.time()
        try:
            # Simple self-check
            latency = (time.time() - start) * 1000
            return CheckResult(
                name="api",
                status=HealthStatus.HEALTHY,
                message="API is responsive",
                latency_ms=latency,
            )
        except Exception as e:
            return CheckResult(
                name="api",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def check_supabase(self) -> CheckResult:
        """Check Supabase database connectivity."""
        start = time.time()
        try:
            from app.services.supabase import get_supabase_client

            client = get_supabase_client()
            # Simple query to test connection
            result = client.table("foodos2_food_items").select("id").limit(1).execute()

            latency = (time.time() - start) * 1000
            return CheckResult(
                name="supabase",
                status=HealthStatus.HEALTHY,
                message="Database connected",
                latency_ms=latency,
                details={"connected": True},
            )
        except Exception as e:
            return CheckResult(
                name="supabase",
                status=HealthStatus.UNHEALTHY,
                message=f"Database error: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def check_barcode_cache(self) -> CheckResult:
        """Check barcode SQLite cache."""
        start = time.time()
        try:
            from app.config import get_settings
            settings = get_settings()
            cache_path = Path(settings.data_dir) / "barcode_cache.db"

            if cache_path.exists():
                size_mb = cache_path.stat().st_size / (1024 * 1024)
                return CheckResult(
                    name="barcode_cache",
                    status=HealthStatus.HEALTHY,
                    message=f"Cache exists ({size_mb:.1f} MB)",
                    latency_ms=(time.time() - start) * 1000,
                    details={"size_mb": round(size_mb, 2), "path": str(cache_path)},
                )
            else:
                return CheckResult(
                    name="barcode_cache",
                    status=HealthStatus.DEGRADED,
                    message="Cache not initialized",
                    latency_ms=(time.time() - start) * 1000,
                )
        except Exception as e:
            return CheckResult(
                name="barcode_cache",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def check_usda_cache(self) -> CheckResult:
        """Check USDA SQLite cache."""
        start = time.time()
        try:
            from app.config import get_settings
            settings = get_settings()
            cache_path = Path(settings.data_dir) / "usda_cache.db"

            if cache_path.exists():
                size_mb = cache_path.stat().st_size / (1024 * 1024)
                return CheckResult(
                    name="usda_cache",
                    status=HealthStatus.HEALTHY,
                    message=f"Cache exists ({size_mb:.1f} MB)",
                    latency_ms=(time.time() - start) * 1000,
                    details={"size_mb": round(size_mb, 2), "path": str(cache_path)},
                )
            else:
                return CheckResult(
                    name="usda_cache",
                    status=HealthStatus.DEGRADED,
                    message="Cache not initialized",
                    latency_ms=(time.time() - start) * 1000,
                )
        except Exception as e:
            return CheckResult(
                name="usda_cache",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def check_open_food_facts(self) -> CheckResult:
        """Check Open Food Facts API connectivity."""
        start = time.time()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Simple API test with known product
                response = await client.get(
                    "https://world.openfoodfacts.org/api/v2/product/737628064502",
                    params={"fields": "code,product_name"}
                )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                return CheckResult(
                    name="open_food_facts",
                    status=HealthStatus.HEALTHY,
                    message="API reachable",
                    latency_ms=latency,
                )
            else:
                return CheckResult(
                    name="open_food_facts",
                    status=HealthStatus.DEGRADED,
                    message=f"API returned {response.status_code}",
                    latency_ms=latency,
                )
        except Exception as e:
            return CheckResult(
                name="open_food_facts",
                status=HealthStatus.UNHEALTHY,
                message=f"API unreachable: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def check_document_ai(self) -> CheckResult:
        """Check Google Document AI configuration."""
        start = time.time()
        try:
            from app.services.receipts import get_receipt_service

            service = get_receipt_service()
            latency = (time.time() - start) * 1000

            if service.is_enabled:
                return CheckResult(
                    name="document_ai",
                    status=HealthStatus.HEALTHY,
                    message="Configured and enabled",
                    latency_ms=latency,
                    details={"enabled": True},
                )
            else:
                return CheckResult(
                    name="document_ai",
                    status=HealthStatus.DEGRADED,
                    message="Not configured (credentials missing)",
                    latency_ms=latency,
                    details={"enabled": False},
                )
        except Exception as e:
            return CheckResult(
                name="document_ai",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def check_tesseract(self) -> CheckResult:
        """Check Tesseract OCR availability."""
        start = time.time()
        try:
            import subprocess
            result = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            latency = (time.time() - start) * 1000

            if result.returncode == 0:
                version = result.stdout.split("\n")[0] if result.stdout else "unknown"
                return CheckResult(
                    name="tesseract",
                    status=HealthStatus.HEALTHY,
                    message=f"Installed: {version}",
                    latency_ms=latency,
                    details={"version": version},
                )
            else:
                return CheckResult(
                    name="tesseract",
                    status=HealthStatus.DEGRADED,
                    message="Not installed",
                    latency_ms=latency,
                )
        except FileNotFoundError:
            return CheckResult(
                name="tesseract",
                status=HealthStatus.DEGRADED,
                message="Not installed (optional)",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="tesseract",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )


# Singleton
_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get health checker singleton."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker
