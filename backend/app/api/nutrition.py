"""
Nutrition API endpoints.

Provides comprehensive nutrition calculations with USDA micronutrient data
and RDA (Recommended Daily Allowance) tracking.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.nutrition import (
    NutritionSummary,
    DailyNutritionStats,
    NutritionAnalytics,
)
from app.services.nutrition import get_nutrition_service

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


@router.get("/daily/{user_id}")
async def get_daily_nutrition(
    user_id: str,
    target_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    include_supplements: bool = Query(True),
    include_planned: bool = Query(False, description="Include all planned meals, not just consumed"),
) -> DailyNutritionStats:
    """Get comprehensive nutrition stats for a single day.

    Returns:
    - Macros (calories, protein, carbs, fat, fiber, sodium)
    - Top micronutrients with RDA percentages
    - Vitamin and mineral scores
    - Comparison to target calories
    """
    import logging
    logger = logging.getLogger(__name__)

    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        parsed_date = date.today()

    try:
        svc = get_nutrition_service()
        return await svc.get_daily_stats(user_id, parsed_date, include_supplements, include_planned)
    except Exception as e:
        logger.error(f"Error getting daily nutrition for {user_id} on {parsed_date}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get nutrition: {str(e)}")


@router.get("/analytics/{user_id}")
async def get_nutrition_analytics(
    user_id: str,
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    days: Optional[int] = Query(None, description="Number of days (alternative to end_date)"),
) -> NutritionAnalytics:
    """Get comprehensive nutrition analytics over a date range.

    Returns:
    - Daily stats for each day
    - Average daily nutrition with RDA tracking
    - Calorie and protein trends
    - Top nutrients and deficiencies
    - Nutrition and consistency scores
    """
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_date format")

    if end_date:
        try:
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    elif days:
        end = start + timedelta(days=days - 1)
    else:
        end = date.today()

    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 90 days")

    svc = get_nutrition_service()
    return await svc.get_nutrition_analytics(user_id, start, end)


@router.get("/week/{user_id}")
async def get_weekly_nutrition(
    user_id: str,
    week_start: Optional[str] = Query(None, description="Week start date (defaults to current week)"),
) -> NutritionAnalytics:
    """Get nutrition analytics for a week.

    Convenience endpoint for weekly view.
    """
    if week_start:
        try:
            start = date.fromisoformat(week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid week_start format")
    else:
        # Get Monday of current week
        today = date.today()
        start = today - timedelta(days=today.weekday())

    end = start + timedelta(days=6)

    svc = get_nutrition_service()
    return await svc.get_nutrition_analytics(user_id, start, end)


@router.get("/rda")
async def get_rda_reference():
    """Get RDA (Recommended Daily Allowance) reference data.

    Returns the reference values used for calculating RDA percentages.
    """
    from app.models.nutrition import RDA_REFERENCE
    return {
        "source": "NIH Office of Dietary Supplements",
        "notes": "Values for adult males. Women may need different amounts for some nutrients (e.g., iron: 18mg).",
        "nutrients": RDA_REFERENCE,
    }
