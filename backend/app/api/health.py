"""Health check endpoints."""

import platform
import psutil
from datetime import datetime

from fastapi import APIRouter

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
