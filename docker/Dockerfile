# slop-pi FastAPI Backend
# Optimized for Raspberry Pi (ARM64)

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

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
