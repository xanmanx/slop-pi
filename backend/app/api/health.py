"""Health check endpoints."""

import platform
import psutil
from datetime import datetime

from fastapi import APIRouter

from app.services.healthcheck import get_health_checker, HealthStatus

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/detailed")
async def detailed_health():
    """Detailed health check with system info."""
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count()

    # Memory
    memory = psutil.virtual_memory()
    memory_used_gb = memory.used / (1024**3)
    memory_total_gb = memory.total / (1024**3)

    # Disk
    disk = psutil.disk_usage("/")
    disk_used_gb = disk.used / (1024**3)
    disk_total_gb = disk.total / (1024**3)

    # Temperature (Pi-specific)
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        if "cpu_thermal" in temps:
            temp = temps["cpu_thermal"][0].current
    except Exception:
        pass

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "system": {
            "platform": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "percent": cpu_percent,
            "cores": cpu_count,
        },
        "memory": {
            "used_gb": round(memory_used_gb, 2),
            "total_gb": round(memory_total_gb, 2),
            "percent": memory.percent,
        },
        "disk": {
            "used_gb": round(disk_used_gb, 2),
            "total_gb": round(disk_total_gb, 2),
            "percent": disk.percent,
        },
        "temperature_c": temp,
    }


@router.get("/health/services")
async def services_health():
    """
    Comprehensive health check of all services.

    Checks:
    - API responsiveness
    - Supabase database
    - Barcode cache (SQLite)
    - USDA cache (SQLite)
    - Open Food Facts API
    - Document AI (Google)
    - Tesseract OCR
    """
    checker = get_health_checker()
    report = await checker.run_all_checks()

    return report.to_dict()


@router.get("/health/ready")
async def readiness_check():
    """
    Kubernetes-style readiness check.

    Returns 200 if service is ready to receive traffic.
    Returns 503 if critical services are down.
    """
    checker = get_health_checker()
    report = await checker.run_all_checks()

    # Check critical services
    critical_services = ["api", "supabase"]
    critical_healthy = all(
        c.status == HealthStatus.HEALTHY
        for c in report.checks
        if c.name in critical_services
    )

    if critical_healthy:
        return {"ready": True, "status": report.status.value}
    else:
        from fastapi import Response
        return Response(
            content='{"ready": false}',
            status_code=503,
            media_type="application/json"
        )


@router.get("/health/live")
async def liveness_check():
    """
    Kubernetes-style liveness check.

    Returns 200 if the process is alive.
    This is a simple check - if we can respond, we're alive.
    """
    return {"live": True, "timestamp": datetime.utcnow().isoformat()}
