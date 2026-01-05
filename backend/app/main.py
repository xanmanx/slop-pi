"""
slop-pi: FastAPI backend for meal planning & nutrition tracking.

Run with: uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api import health, usda, ai, cron
from app.services.usda import USDAService
from app.jobs.scheduler import start_scheduler, shutdown_scheduler

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    logger.info("Starting slop-pi backend...")

    # Initialize USDA cache
    usda_service = USDAService()
    await usda_service.init_cache()
    app.state.usda_service = usda_service
    logger.info("USDA cache initialized")

    # Start background scheduler
    start_scheduler()
    logger.info("Scheduler started")

    yield

    # Shutdown
    logger.info("Shutting down slop-pi backend...")
    shutdown_scheduler()
    await usda_service.close()


app = FastAPI(
    title="slop-pi",
    description="Meal planning & nutrition tracking API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://slop.local:3000",
        "https://slop.vercel.app",  # Update with your Vercel domain
        "*",  # For development - restrict in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(usda.router, prefix="/api/usda", tags=["usda"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(cron.router, prefix="/api/cron", tags=["cron"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "slop-pi",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=not settings.is_production,
    )
