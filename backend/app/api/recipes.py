"""
Recipe API endpoints.

Provides recipe flattening, nutrition calculation, and batch operations.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.models.recipes import RecipeFlattened, BatchRecipeRequest
from app.services.recipes import (
    flatten_recipe,
    flatten_recipes_batch,
    clear_recipe_caches,
)

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


class FlattenRequest(BaseModel):
    """Request to flatten a single recipe."""
    recipe_id: str
    user_id: str
    scale_factor: float = 1.0
    include_micronutrients: bool = True
    include_rda: bool = True


class BatchFlattenRequest(BaseModel):
    """Request to flatten multiple recipes."""
    recipe_ids: list[str]
    user_id: str
    scale_factors: Optional[dict[str, float]] = None
    include_micronutrients: bool = True


@router.post("/flatten")
async def flatten_single_recipe(request: FlattenRequest) -> RecipeFlattened:
    """Flatten a single recipe into its component ingredients.

    This traverses the recipe DAG (Directed Acyclic Graph) and returns:
    - All ingredient components with amounts
    - Complete nutrition (macros + micronutrients with RDA)
    - Recipe metadata (prep time, steps)

    Results are cached for 10 minutes.
    """
    return await flatten_recipe(
        recipe_id=request.recipe_id,
        user_id=request.user_id,
        scale_factor=request.scale_factor,
        include_micronutrients=request.include_micronutrients,
        include_rda=request.include_rda,
    )


@router.get("/flatten/{recipe_id}")
async def flatten_recipe_get(
    recipe_id: str,
    user_id: str = Query(...),
    scale: float = Query(1.0, ge=0.1, le=10.0),
    include_rda: bool = Query(True),
) -> RecipeFlattened:
    """GET endpoint for flattening a recipe.

    Same as POST /flatten but via GET for simpler integration.
    """
    return await flatten_recipe(
        recipe_id=recipe_id,
        user_id=user_id,
        scale_factor=scale,
        include_micronutrients=True,
        include_rda=include_rda,
    )


@router.post("/flatten/batch")
async def flatten_recipes_batch_endpoint(request: BatchFlattenRequest) -> list[RecipeFlattened]:
    """Flatten multiple recipes in parallel.

    This is significantly faster than calling /flatten multiple times
    because:
    1. Recipe graph context is loaded once and shared
    2. All recipes are processed concurrently
    3. Results are cached individually

    Use this when loading a day's meals or weekly plan.
    """
    if len(request.recipe_ids) > 50:
        raise HTTPException(
            status_code=400,
            detail="Cannot flatten more than 50 recipes at once"
        )

    return await flatten_recipes_batch(
        recipe_ids=request.recipe_ids,
        user_id=request.user_id,
        scale_factors=request.scale_factors,
    )


@router.delete("/cache")
async def clear_cache(
    user_id: Optional[str] = Query(None, description="Clear cache for specific user only"),
) -> dict:
    """Clear recipe caches.

    Useful after:
    - Editing a recipe's ingredients
    - Changing ingredient preferences
    - Updating food item nutrition data
    """
    clear_recipe_caches(user_id)
    return {
        "success": True,
        "message": f"Cache cleared for {'user ' + user_id if user_id else 'all users'}",
    }


@router.get("/cache/stats")
async def get_cache_stats() -> dict:
    """Get recipe cache statistics."""
    from app.services.recipes import _graph_cache, _flatten_cache
    import time

    now = time.time()

    graph_stats = {}
    for user_id, (cached_at, ctx) in _graph_cache.items():
        age_seconds = now - cached_at
        graph_stats[user_id[:8] + "..."] = {
            "items": len(ctx.item_map),
            "recipes": len(ctx.edges_by_parent),
            "age_seconds": int(age_seconds),
        }

    return {
        "graph_cache": {
            "users_cached": len(_graph_cache),
            "by_user": graph_stats,
        },
        "flatten_cache": {
            "recipes_cached": len(_flatten_cache),
        },
    }
