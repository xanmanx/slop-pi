# slop-pi: Raspberry Pi Optimized Docker Image
#
# Optimized for ARM64 (Raspberry Pi 4/5)
# Uses uv for fast dependency installation
# Multi-worker for utilizing all CPU cores

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy everything needed for the build
COPY pyproject.toml README.md ./
COPY backend/app ./backend/app

# Install the package and dependencies
RUN uv pip install --system .

# Move app to correct location for runtime
RUN mv backend/app ./app && rm -rf backend

# Create data directory for SQLite cache (mounted via volume at runtime)
RUN mkdir -p /app/data /app/logs

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATA_DIR=/app/data
ENV USDA_CACHE_DB=/app/data/usda_cache.db

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
# Use 2 workers for Raspberry Pi (balances memory vs CPU usage)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
