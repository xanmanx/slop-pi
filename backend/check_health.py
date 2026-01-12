#!/usr/bin/env python3
"""
Quick health check script.

Usage:
    python check_health.py          # Run all health checks
    python check_health.py --json   # Output as JSON
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.healthcheck import get_health_checker, HealthStatus


COLORS = {
    HealthStatus.HEALTHY: "\033[92m",    # Green
    HealthStatus.DEGRADED: "\033[93m",   # Yellow
    HealthStatus.UNHEALTHY: "\033[91m",  # Red
    HealthStatus.UNKNOWN: "\033[90m",    # Gray
}
RESET = "\033[0m"


async def main():
    parser = argparse.ArgumentParser(description="Check system health")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    checker = get_health_checker()
    report = await checker.run_all_checks()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    # Pretty print
    print("\n" + "=" * 60)
    print(f"  SLOP-PI HEALTH CHECK")
    print(f"  Version: {report.version}")
    print(f"  Time: {report.timestamp.isoformat()}")
    print("=" * 60 + "\n")

    # Overall status
    color = COLORS.get(report.status, "")
    print(f"  Overall: {color}{report.status.value.upper()}{RESET}")
    print(f"  Summary: {report.healthy_count}/{report.total_count} checks passing\n")

    # Individual checks
    print("  " + "-" * 56)
    print(f"  {'Service':<20} {'Status':<12} {'Latency':<10} Message")
    print("  " + "-" * 56)

    for check in report.checks:
        color = COLORS.get(check.status, "")
        status = f"{color}{check.status.value:<12}{RESET}"
        latency = f"{check.latency_ms:.0f}ms" if check.latency_ms else "-"
        print(f"  {check.name:<20} {status} {latency:<10} {check.message}")

    print("  " + "-" * 56 + "\n")

    # Exit code based on status
    if report.status == HealthStatus.UNHEALTHY:
        sys.exit(1)
    elif report.status == HealthStatus.DEGRADED:
        sys.exit(0)  # Degraded is still operational
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
