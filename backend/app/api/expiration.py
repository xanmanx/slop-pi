"""Expiration date management API endpoints."""

from datetime import date
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Literal

from app.models.expiration import (
    ExpirationSetRequest,
    ExpirationSetResponse,
    ExpiringItemsResponse,
    ShelfLifeCorrectionRequest,
    ShelfLifeCorrectionResponse,
    CategoryDefaultsResponse,
    ExpirationStatsResponse,
    InventoryExpiration,
)
from app.services.expiration import get_expiration_service

router = APIRouter(prefix="/api/expiration", tags=["expiration"])


@router.get("/inventory", response_model=list[InventoryExpiration])
async def get_inventory_with_expiration(
    user_id: str = Query(..., description="User ID"),
    include_no_expiration: bool = Query(True, description="Include items without expiration dates"),
):
    """
    Get all inventory items with expiration information.

    Items are sorted by expiration date (soonest first).
    Includes suggested expiration dates for items without one set.
    """
    expiration_service = get_expiration_service()

    return await expiration_service.get_inventory_with_expiration(user_id, include_no_expiration)


@router.get("/expiring-soon", response_model=ExpiringItemsResponse)
async def get_expiring_soon(
    user_id: str = Query(..., description="User ID"),
    days: int = Query(7, ge=1, le=30, description="Days threshold"),
):
    """
    Get items expiring within N days.

    Also includes already expired items.
    Use this for "use soon" reminders and waste prevention.
    """
    expiration_service = get_expiration_service()

    return await expiration_service.get_expiring_soon(user_id, days)


@router.post("/set/{inventory_id}", response_model=ExpirationSetResponse)
async def set_expiration(
    inventory_id: str,
    body: ExpirationSetRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Set or update expiration date for an inventory item.

    Can either:
    - Set a specific expiration date
    - Use the suggested expiration based on food category
    - Update storage type (pantry/refrigerator/freezer)
    """
    expiration_service = get_expiration_service()

    return await expiration_service.set_expiration(
        user_id=user_id,
        inventory_id=inventory_id,
        expiration_date=body.expiration_date,
        purchase_date=body.purchase_date,
        storage_type=body.storage_type,
        use_suggested=body.use_suggested,
    )


@router.post("/learned", response_model=ShelfLifeCorrectionResponse)
async def record_shelf_life_correction(
    body: ShelfLifeCorrectionRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Record a shelf life correction for learning.

    When an item goes bad earlier or lasts longer than expected,
    record the actual shelf life to improve future predictions.
    """
    expiration_service = get_expiration_service()

    return await expiration_service.record_correction(
        user_id=user_id,
        food_item_id=body.food_item_id,
        storage_type=body.storage_type,
        expected_days=body.expected_days,
        actual_days=body.actual_days,
    )


@router.get("/defaults/{category}", response_model=CategoryDefaultsResponse)
async def get_category_defaults(
    category: str,
):
    """
    Get default shelf life for a food category.

    Returns shelf life for pantry, refrigerator, and freezer storage,
    along with subcategories if available.

    Categories include: dairy, meat, seafood, produce_vegetables,
    produce_fruits, bread_bakery, condiments, pantry_staples, etc.
    """
    expiration_service = get_expiration_service()

    return expiration_service.get_category_defaults(category)


@router.get("/suggest")
async def suggest_expiration(
    food_item_name: str = Query(..., description="Food item name"),
    food_item_kind: str = Query("ingredient", description="Food kind"),
    storage_type: Literal["pantry", "refrigerator", "freezer"] = Query("refrigerator"),
    purchase_date: Optional[date] = Query(None, description="Purchase date"),
):
    """
    Get a suggested expiration date for a food item.

    Based on the food name and storage type, returns a suggested
    expiration date using USDA FoodKeeper guidelines.
    """
    expiration_service = get_expiration_service()

    suggested = expiration_service.suggest_expiration(
        food_item_name=food_item_name,
        food_item_kind=food_item_kind,
        purchase_date=purchase_date,
        storage_type=storage_type,
    )

    days_until = (suggested - date.today()).days if suggested else None

    return {
        "food_item_name": food_item_name,
        "storage_type": storage_type,
        "suggested_expiration_date": suggested.isoformat() if suggested else None,
        "days_until_expiry": days_until,
    }


@router.get("/stats/summary", response_model=ExpirationStatsResponse)
async def get_expiration_stats(
    user_id: str = Query(..., description="User ID"),
):
    """Get expiration tracking statistics."""
    expiration_service = get_expiration_service()

    return await expiration_service.get_stats(user_id)


@router.get("/categories")
async def list_categories():
    """List all available food categories with shelf life data."""
    expiration_service = get_expiration_service()

    categories = list(expiration_service.shelf_life_data.get("categories", {}).keys())

    return {
        "categories": categories,
        "count": len(categories),
    }
