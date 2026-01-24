"""
Grocery list API endpoints.

Provides grocery list generation and management.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.grocery import (
    GroceryGenerationRequest,
    GroceryList,
    GroceryListRecord,
    GroceryListWithItems,
    SaveGroceryListRequest,
    CheckItemRequest,
)
from app.services.grocery import generate_grocery_list
from app.services.grocery_lists import (
    save_grocery_list,
    get_grocery_lists,
    get_grocery_list,
    update_item_checked,
    delete_grocery_list,
    complete_grocery_list,
    archive_grocery_list,
)

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


@router.get("/debug/{user_id}")
async def debug_grocery(
    user_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict:
    """Debug endpoint to trace grocery generation issues."""
    from app.services.supabase import get_supabase_client, TABLES
    from app.services.recipes import flatten_recipe_auto_owner

    client = get_supabase_client()

    # Load plan entries
    entries_result = client.table(TABLES["plan"]).select("*").eq(
        "user_id", user_id
    ).gte(
        "planned_date", str(start_date)
    ).lte(
        "planned_date", str(end_date)
    ).execute()
    entries = entries_result.data or []

    # Build item_map - first load items by ID from plan entries
    needed_ids = list(set(e["food_item_id"] for e in entries))
    item_map = {}

    # Load plan items directly by ID
    if needed_ids:
        for i in range(0, len(needed_ids), 100):
            batch = needed_ids[i:i+100]
            batch_result = client.table(TABLES["items"]).select("id,name,kind,user_id,is_public").in_("id", batch).execute()
            for item in (batch_result.data or []):
                item_map[item["id"]] = item

    # Also load user's items with higher limit
    access_filter = f"user_id.eq.{user_id},user_id.is.null,is_public.eq.true"
    items_result = client.table(TABLES["items"]).select("id,name,kind,user_id,is_public").or_(access_filter).limit(5000).execute()
    for item in (items_result.data or []):
        if item["id"] not in item_map:
            item_map[item["id"]] = item

    # Track processing
    debug_entries = []
    for entry in entries[:10]:  # First 10 entries only
        fid = entry["food_item_id"]
        item = item_map.get(fid)
        entry_debug = {
            "food_item_id": fid,
            "found_in_item_map": item is not None,
            "item_name": item.get("name") if item else None,
            "item_kind": item.get("kind") if item else None,
        }

        if item and item.get("kind") not in ("ingredient", "product"):
            # Try to flatten
            try:
                flattened = await flatten_recipe_auto_owner(
                    fid, user_id, 1.0,
                    include_micronutrients=False, include_rda=False
                )
                entry_debug["ingredients_count"] = len(flattened.ingredients)
                entry_debug["ingredient_names"] = [i.ingredient_name for i in flattened.ingredients[:3]]
            except Exception as e:
                entry_debug["flatten_error"] = str(e)

        debug_entries.append(entry_debug)

    return {
        "entries_count": len(entries),
        "item_map_size": len(item_map),
        "sample_item_map_ids": list(item_map.keys())[:5],
        "debug_entries": debug_entries,
    }


@router.get("/list/{user_id}", response_model=GroceryList)
async def get_grocery_list_generated(
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


# ============================================================================
# Persistent Grocery List Endpoints
# ============================================================================


@router.post("/lists", response_model=dict)
async def save_list(request: SaveGroceryListRequest) -> dict:
    """Save a grocery list to the database.

    Returns:
        {id: str, created: bool}
    """
    try:
        list_id = await save_grocery_list(request)
        return {"id": list_id, "created": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lists", response_model=list[GroceryListRecord])
async def get_lists(
    user_id: str = Query(..., description="User ID"),
    status: Optional[str] = Query("active", description="Filter by status: active, completed, archived"),
    limit: int = Query(20, description="Maximum lists to return"),
) -> list[GroceryListRecord]:
    """Get user's saved grocery lists."""
    try:
        return await get_grocery_lists(user_id, status, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lists/{list_id}", response_model=GroceryListWithItems)
async def get_list(
    list_id: str,
    user_id: str = Query(..., description="User ID"),
) -> GroceryListWithItems:
    """Get a specific grocery list with all its items."""
    try:
        return await get_grocery_list(list_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/lists/{list_id}/items/{item_id}", response_model=dict)
async def update_item(
    list_id: str,
    item_id: str,
    request: CheckItemRequest,
    user_id: str = Query(..., description="User ID"),
) -> dict:
    """Update a grocery list item (check/uncheck)."""
    try:
        success = await update_item_checked(item_id, request.checked, user_id)
        return {"success": success, "item_id": item_id, "checked": request.checked}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/lists/{list_id}", response_model=dict)
async def delete_list(
    list_id: str,
    user_id: str = Query(..., description="User ID"),
) -> dict:
    """Delete a grocery list."""
    try:
        success = await delete_grocery_list(list_id, user_id)
        return {"success": success, "deleted": list_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lists/{list_id}/complete", response_model=dict)
async def complete_list(
    list_id: str,
    user_id: str = Query(..., description="User ID"),
) -> dict:
    """Mark a grocery list as completed."""
    try:
        success = await complete_grocery_list(list_id, user_id)
        return {"success": success, "status": "completed"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lists/{list_id}/archive", response_model=dict)
async def archive_list(
    list_id: str,
    user_id: str = Query(..., description="User ID"),
) -> dict:
    """Archive a grocery list."""
    try:
        success = await archive_grocery_list(list_id, user_id)
        return {"success": success, "status": "archived"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
