# Makefile for slop-pi backend

.PHONY: test test-unit test-integration test-e2e test-coverage health install lint clean

# Install dependencies
install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov httpx pillow

# Run all tests
test:
	python -m pytest tests/ -v

# Run unit tests only (fast)
test-unit:
	python -m pytest tests/unit -v -m unit

# Run integration tests
test-integration:
	python -m pytest tests/integration -v -m integration

# Run E2E tests
test-e2e:
	python -m pytest tests/e2e -v -m e2e

# Run tests with coverage
test-coverage:
	python -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=html:coverage_html

# Quick health check
health:
	@echo "Checking service health..."
	@curl -s http://localhost:8000/api/health/services | python -m json.tool || echo "API not running"

# Health check (detailed)
health-detailed:
	@curl -s http://localhost:8000/api/health/detailed | python -m json.tool || echo "API not running"

# Lint code
lint:
	python -m flake8 app/ --max-line-length=100 --ignore=E501
	python -m mypy app/ --ignore-missing-imports

# Clean up
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name coverage_html -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true

# Run the development server
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run health check from command line
check:
	python -c "import asyncio; from app.services.healthcheck import get_health_checker; \
		async def main(): \
			r = await get_health_checker().run_all_checks(); \
			for c in r.checks: print(f'{c.status.value:10} {c.name:20} {c.message}'); \
		asyncio.run(main())"
