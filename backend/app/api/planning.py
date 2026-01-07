"""
Meal planning API endpoints.

Provides plan generation, batch prep, and household planning.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.models.planning import (
    HouseholdPlanRequest,
    HouseholdPlanResult,
    PlanGenerationRequest,
    PlanGenerationResult,
)
from app.services.planning import (
    clear_batch_prep,
    generate_household_plan,
    generate_plan,
    get_batch_prep_entries,
    get_batch_prep_summary,
    save_plan_entries,
    set_batch_prep,
)

router = APIRouter(prefix="/api/planning", tags=["planning"])


# ============================================================================
# Plan Generation
# ============================================================================

@router.post("/generate", response_model=PlanGenerationResult)
async def generate_meal_plan(request: PlanGenerationRequest) -> PlanGenerationResult:
    """Generate a meal plan for a date range.

    Uses user preferences to select appropriate meals and scale portions
    to hit calorie targets.
    """
    try:
        return await generate_plan(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SavePlanRequest(BaseModel):
    """Request to save generated plan entries."""
    user_id: str
    entries: list[dict]


@router.post("/save")
async def save_generated_plan(request: PlanGenerationRequest) -> dict:
    """Generate and save a meal plan.

    Generates entries and persists them to the database.
    """
    try:
        result = await generate_plan(request)
        if result.entries:
            saved = await save_plan_entries(result.entries, request.user_id)
            return {
                "success": True,
                "entries_created": saved,
                "avg_daily_calories": result.avg_daily_calories,
                "calorie_accuracy_pct": result.calorie_accuracy_pct,
            }
        return {"success": True, "entries_created": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Batch Prep
# ============================================================================

class BatchPrepRequest(BaseModel):
    """Request to set batch prep for entries."""
    user_id: str
    entry_ids: list[str]
    batch_prep_date: date
    batch_prep_time: Optional[str] = None


@router.post("/batch-prep/set")
async def set_batch_prep_entries(request: BatchPrepRequest) -> dict:
    """Mark entries for batch prep on a specific date.

    All specified entries will be prepared together on the batch prep date.
    """
    try:
        updated = await set_batch_prep(
            request.entry_ids,
            request.user_id,
            request.batch_prep_date,
            request.batch_prep_time,
        )
        return {"success": True, "entries_updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ClearBatchPrepRequest(BaseModel):
    """Request to clear batch prep from entries."""
    user_id: str
    entry_ids: list[str]


@router.post("/batch-prep/clear")
async def clear_batch_prep_entries(request: ClearBatchPrepRequest) -> dict:
    """Clear batch prep settings from entries."""
    try:
        updated = await clear_batch_prep(request.entry_ids, request.user_id)
        return {"success": True, "entries_updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-prep/{user_id}/{prep_date}")
async def get_batch_prep_list(user_id: str, prep_date: date) -> dict:
    """Get all entries scheduled for batch prep on a date."""
    try:
        entries = await get_batch_prep_entries(user_id, prep_date)
        return {"date": str(prep_date), "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-prep/{user_id}/{prep_date}/summary")
async def get_batch_prep_session_summary(user_id: str, prep_date: date) -> dict:
    """Get aggregated summary for a batch prep session.

    Returns:
    - All meals being prepped
    - Combined ingredient list with amounts
    - Total nutrition for the session
    """
    try:
        return await get_batch_prep_summary(user_id, prep_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Household Planning
# ============================================================================

@router.post("/household/generate", response_model=HouseholdPlanResult)
async def generate_household_meal_plan(
    request: HouseholdPlanRequest,
) -> HouseholdPlanResult:
    """Generate synchronized meal plans for a household.

    Shared meals (like dinner) are planned once and assigned to all members
    with portions scaled to individual calorie targets.
    """
    try:
        return await generate_household_plan(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
