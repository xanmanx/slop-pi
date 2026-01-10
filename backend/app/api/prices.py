"""Price tracking API endpoints."""

from decimal import Decimal
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models.prices import (
    PriceRecordRequest,
    PriceRecordResponse,
    PriceHistory,
    PriceTrend,
    PriceComparison,
    PriceAlertsResponse,
    PriceStatsResponse,
)
from app.services.prices import get_price_service

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/record", response_model=PriceRecordResponse)
async def record_price(
    body: PriceRecordRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Record a price for a food item.

    Tracks prices over time for trend analysis and comparison shopping.
    Automatically calculates price per 100g if quantity is provided.
    """
    price_service = get_price_service()

    result = await price_service.record_price(
        user_id=user_id,
        food_item_id=body.food_item_id,
        price=body.price,
        quantity_g=body.quantity_g,
        store_name=body.store_name,
        purchase_date=body.purchase_date,
        source="manual",
    )

    return result


@router.get("/{food_item_id}", response_model=PriceHistory)
async def get_price_history(
    food_item_id: str,
    user_id: str = Query(..., description="User ID"),
    days: int = Query(90, ge=1, le=365, description="Days of history"),
):
    """
    Get price history for a food item.

    Returns all recorded prices within the specified time range,
    along with statistics (lowest, highest, average).
    """
    price_service = get_price_service()

    return await price_service.get_price_history(user_id, food_item_id, days)


@router.get("/{food_item_id}/trend", response_model=PriceTrend)
async def get_price_trend(
    food_item_id: str,
    user_id: str = Query(..., description="User ID"),
    days: int = Query(30, ge=7, le=180, description="Days for trend analysis"),
):
    """
    Analyze price trend for a food item.

    Uses linear regression to determine if prices are:
    - Going up
    - Going down
    - Stable

    Also predicts the likely next price.
    """
    price_service = get_price_service()

    return await price_service.analyze_trend(user_id, food_item_id, days)


@router.get("/{food_item_id}/compare", response_model=PriceComparison)
async def compare_prices(
    food_item_id: str,
    user_id: str = Query(..., description="User ID"),
):
    """
    Compare prices across different stores.

    Shows which store has the best price and potential savings.
    """
    price_service = get_price_service()

    return await price_service.compare_prices(user_id, food_item_id)


@router.get("/alerts/drops", response_model=PriceAlertsResponse)
async def get_price_alerts(
    user_id: str = Query(..., description="User ID"),
    min_drop_percent: float = Query(10, ge=1, le=50, description="Minimum price drop percentage"),
    days: int = Query(7, ge=1, le=30, description="Days to look back"),
):
    """
    Get recent price drop alerts.

    Returns items that have dropped in price by at least the specified percentage
    within the specified time range.
    """
    price_service = get_price_service()

    return await price_service.get_price_alerts(user_id, min_drop_percent, days)


@router.get("/stats/summary", response_model=PriceStatsResponse)
async def get_price_stats(
    user_id: str = Query(..., description="User ID"),
):
    """Get price tracking statistics."""
    price_service = get_price_service()

    return await price_service.get_stats(user_id)
