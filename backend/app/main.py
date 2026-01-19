"""
slop-pi: FastAPI backend for meal planning & nutrition tracking.

Run with: uvicorn app.main:app --reload

Architecture:
- Handles all heavy computation (recipe flattening, nutrition calculations)
- Provides comprehensive USDA micronutrient data with RDA tracking
- Runs background jobs for auto-consumption and reminders
- Optimized for Raspberry Pi deployment with aggressive caching
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import health, usda, ai, cron
from app.api import nutrition as nutrition_api
from app.api import recipes as recipes_api
from app.api import grocery as grocery_api
from app.api import planning as planning_api
from app.api import batch_prep as batch_prep_api
from app.api import barcode as barcode_api
# DISABLED: Receipt OCR temporarily disabled while focusing on core features
# from app.api import receipts as receipts_api
from app.api import prices as prices_api
from app.api import expiration as expiration_api
from app.services.usda import USDAService
from app.services.barcode import BarcodeService
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

    # Initialize Barcode cache
    barcode_service = BarcodeService()
    await barcode_service.init_cache()
    app.state.barcode_service = barcode_service
    logger.info("Barcode cache initialized")

    # Start background scheduler
    start_scheduler()
    logger.info("Scheduler started")

    yield

    # Shutdown
    logger.info("Shutting down slop-pi backend...")
    shutdown_scheduler()
    await usda_service.close()
    await barcode_service.close()


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
        "https://slxp.app",
        "*",  # For development - restrict in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    """Verify API key for protected endpoints."""
    # Allow these paths without auth
    public_paths = ["/", "/health", "/health/detailed", "/docs", "/openapi.json", "/redoc"]

    # Also allow recipe endpoints (secured by user_id in payload)
    recipe_prefixes = [
        "/api/recipes/", "/api/nutrition/", "/api/grocery/", "/api/planning/",
        "/api/batch-prep/", "/api/barcode/", "/api/receipts/", "/api/prices/", "/api/expiration/"
    ]
    if any(request.url.path.startswith(prefix) for prefix in recipe_prefixes):
        return await call_next(request)

    if request.url.path in public_paths:
        return await call_next(request)

    # Check API key
    api_key = request.headers.get("X-API-Key")
    expected_key = settings.pi_api_key

    # If no key configured, allow all (dev mode)
    if not expected_key:
        logger.warning("PI_API_KEY not set - API is unprotected!")
        return await call_next(request)

    if api_key != expected_key:
        logger.warning(f"Invalid API key attempt from {request.client.host}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key"}
        )

    return await call_next(request)


# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(usda.router, prefix="/api/usda", tags=["usda"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(cron.router, prefix="/api/cron", tags=["cron"])
app.include_router(nutrition_api.router)  # /api/nutrition
app.include_router(recipes_api.router)  # /api/recipes
app.include_router(grocery_api.router)  # /api/grocery
app.include_router(planning_api.router)  # /api/planning
app.include_router(batch_prep_api.router)  # /api/batch-prep
app.include_router(barcode_api.router)  # /api/barcode
# DISABLED: Receipt OCR temporarily disabled while focusing on core features
# app.include_router(receipts_api.router)  # /api/receipts
app.include_router(prices_api.router)  # /api/prices
app.include_router(expiration_api.router)  # /api/expiration


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "slop-pi",
        "version": "2.3.1",
        "description": "Meal planning & nutrition API with barcode lookup and price tracking",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "usda": "/api/usda",
            "ai": "/api/ai",
            "nutrition": "/api/nutrition",
            "recipes": "/api/recipes",
            "grocery": "/api/grocery",
            "planning": "/api/planning",
            "batch-prep": "/api/batch-prep",
            "barcode": "/api/barcode",
            # "receipts": "/api/receipts",  # Temporarily disabled
            "prices": "/api/prices",
            "expiration": "/api/expiration",
            "cron": "/api/cron",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=not settings.is_production,
    )
