"""
Grocery list API endpoints.

Provides grocery list generation and management.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.grocery import GroceryGenerationRequest, GroceryList
from app.services.grocery import generate_grocery_list

router = APIRouter(prefix="/api/grocery", tags=["grocery"])


@router.post("/generate", response_model=GroceryList)
async def generate_list(request: GroceryGenerationRequest) -> GroceryList:
    """Generate a grocery list for a date range.

    Aggregates ingredients from:
    - Meal plan entries
    - Reorder schedules (when inventory below threshold)
    - Supplement schedules

    Subtracts current inventory and groups by category.
    """
    try:
        return await generate_grocery_list(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list/{user_id}", response_model=GroceryList)
async def get_grocery_list(
    user_id: str,
    start_date: date = Query(..., description="Start date for grocery list"),
    end_date: date = Query(..., description="End date for grocery list"),
    include_meals: bool = Query(True, description="Include meal plan items"),
    include_reorders: bool = Query(True, description="Include reorder items"),
    include_supplements: bool = Query(True, description="Include supplements"),
    subtract_inventory: bool = Query(True, description="Subtract current inventory"),
    include_household: bool = Query(False, description="Include household members"),
    household_user_ids: Optional[str] = Query(None, description="Comma-separated household user IDs"),
) -> GroceryList:
    """Get grocery list for a user and date range.

    This is a convenience GET endpoint that wraps the POST generation.
    """
    try:
        # Parse household IDs
        household_ids = None
        if household_user_ids:
            household_ids = [uid.strip() for uid in household_user_ids.split(",")]

        request = GroceryGenerationRequest(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            include_meals=include_meals,
            include_reorders=include_reorders,
            include_supplements=include_supplements,
            subtract_inventory=subtract_inventory,
            include_household=include_household,
            household_user_ids=household_ids,
        )

        return await generate_grocery_list(request)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
