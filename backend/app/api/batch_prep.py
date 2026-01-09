"""
Batch Prep API endpoints.

Provides heavy compute for batch meal preparation:
- Recipe flattening and ingredient aggregation
- Meal grouping for efficient display
- Organized data structure for frontend
"""

from fastapi import APIRouter, HTTPException

from app.models.batch_prep import (
    BatchPrepComputeRequest,
    BatchPrepComputeResponse,
)
from app.services.batch_prep import compute_batch_prep

router = APIRouter(prefix="/api/batch-prep", tags=["batch-prep"])


@router.post("/compute")
async def compute_batch_prep_endpoint(
    request: BatchPrepComputeRequest,
) -> BatchPrepComputeResponse:
    """
    Compute batch prep data for a set of plan entries.

    This is the main heavy-compute endpoint for batch meal preparation.
    It handles:
    1. Loading all plan entries
    2. Grouping identical meals together (shows meal once with count)
    3. Flattening all recipe DAGs in parallel
    4. Aggregating ingredients across all meals
    5. Returning organized display structure

    The response includes:
    - `grouped_meals`: Unique meals with counts and instructions
    - `aggregated_ingredients`: Total ingredients needed across all meals
    - Timing and nutrition totals

    Example:
    ```json
    {
        "user_id": "abc123",
        "plan_entry_ids": ["entry1", "entry2", "entry3"]
    }
    ```

    If entries 1 and 2 are the same meal, response will show:
    - 2 grouped_meals (unique meals)
    - 3 total_meal_count (including duplicates)
    """
    if not request.plan_entry_ids:
        return BatchPrepComputeResponse()

    if len(request.plan_entry_ids) > 100:
        raise HTTPException(
            status_code=400,
            detail="Cannot process more than 100 plan entries at once",
        )

    return await compute_batch_prep(
        user_id=request.user_id,
        plan_entry_ids=request.plan_entry_ids,
        include_batch_instructions=request.include_batch_instructions,
    )
