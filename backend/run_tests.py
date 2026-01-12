#!/usr/bin/env python3
"""
Test runner script with coverage reporting.

Usage:
    python run_tests.py              # Run all tests
    python run_tests.py unit         # Run unit tests only
    python run_tests.py integration  # Run integration tests only
    python run_tests.py e2e          # Run E2E tests only
    python run_tests.py --coverage   # Run with coverage report
    python run_tests.py --fast       # Skip slow tests
"""

import subprocess
import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run tests")
    parser.add_argument(
        "test_type",
        nargs="?",
        choices=["all", "unit", "integration", "e2e"],
        default="all",
        help="Type of tests to run",
    )
    parser.add_argument(
        "--coverage", "-c",
        action="store_true",
        help="Run with coverage report",
    )
    parser.add_argument(
        "--fast", "-f",
        action="store_true",
        help="Skip slow tests",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--failfast", "-x",
        action="store_true",
        help="Stop on first failure",
    )

    args = parser.parse_args()

    # Build pytest command
    cmd = ["python", "-m", "pytest"]

    # Test selection
    if args.test_type == "unit":
        cmd.extend(["-m", "unit", "tests/unit"])
    elif args.test_type == "integration":
        cmd.extend(["-m", "integration", "tests/integration"])
    elif args.test_type == "e2e":
        cmd.extend(["-m", "e2e", "tests/e2e"])
    else:
        cmd.append("tests/")

    # Options
    if args.fast:
        cmd.extend(["-m", "not slow"])

    if args.verbose:
        cmd.append("-v")

    if args.failfast:
        cmd.append("-x")

    # Coverage
    if args.coverage:
        cmd = [
            "python", "-m", "pytest",
            "--cov=app",
            "--cov-report=term-missing",
            "--cov-report=html:coverage_html",
            "--cov-fail-under=50",
        ] + cmd[3:]  # Remove initial pytest args

    print(f"Running: {' '.join(cmd)}")
    print("=" * 60)

    # Run tests
    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if args.coverage and result.returncode == 0:
        print("\n" + "=" * 60)
        print("Coverage report generated: coverage_html/index.html")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
