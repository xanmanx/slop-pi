"""USDA FoodData Central API endpoints with local SQLite caching."""

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

router = APIRouter()


class USDASearchRequest(BaseModel):
    """Search request body."""
    query: str
    page_size: int = 25
    data_types: list[str] = ["Foundation", "SR Legacy"]


class USDAImportRequest(BaseModel):
    """Import request for hydrating Supabase."""
    query: str | None = None
    fdc_id: str | None = None
    operation: str = "search"  # search, import_fdc, resolve_ingredient


@router.get("/search")
async def search_usda(
    request: Request,
    query: str = Query(..., min_length=1, description="Search query"),
    page_size: int = Query(25, ge=1, le=50),
    use_cache: bool = Query(True, description="Use local SQLite cache"),
):
    """
    Search USDA FoodData Central.

    Results are cached locally in SQLite for instant subsequent lookups.
    """
    usda_service = request.app.state.usda_service

    # Check cache first
    if use_cache:
        cached = await usda_service.search_cache(query, page_size)
        if cached:
            return {
                "source": "cache",
                "total_hits": len(cached),
                "foods": cached,
            }

    # Hit USDA API
    try:
        results = await usda_service.search_api(
            query=query,
            page_size=page_size,
            data_types=["Foundation", "SR Legacy"],
        )

        # Cache results
        if results.get("foods"):
            await usda_service.cache_foods(results["foods"], query)

        return {
            "source": "api",
            "total_hits": results.get("totalHits", 0),
            "foods": results.get("foods", []),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"USDA API error: {str(e)}")


@router.get("/food/{fdc_id}")
async def get_food_by_id(
    request: Request,
    fdc_id: str,
    use_cache: bool = Query(True),
):
    """Get a specific food by FDC ID."""
    usda_service = request.app.state.usda_service

    # Check cache
    if use_cache:
        cached = await usda_service.get_cached_food(fdc_id)
        if cached:
            return {"source": "cache", "food": cached}

    # Hit API
    try:
        food = await usda_service.get_food_api(fdc_id)
        if food:
            await usda_service.cache_single_food(food)
        return {"source": "api", "food": food}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"USDA API error: {str(e)}")


@router.post("/hydrate")
async def hydrate_to_supabase(
    request: Request,
    body: USDAImportRequest,
):
    """
    Import USDA foods into Supabase foodos2_food_items table.

    Operations:
    - search: Search and import matching foods
    - import_fdc: Import a specific FDC ID
    - resolve_ingredient: Find best match for an ingredient name
    """
    usda_service = request.app.state.usda_service

    if body.operation == "resolve_ingredient":
        if not body.query:
            raise HTTPException(status_code=400, detail="Missing query for resolve_ingredient")

        result = await usda_service.resolve_ingredient(body.query)
        return result

    elif body.operation == "import_fdc":
        if not body.fdc_id:
            raise HTTPException(status_code=400, detail="Missing fdc_id")

        result = await usda_service.import_single_food(body.fdc_id)
        return result

    else:  # search
        if not body.query:
            raise HTTPException(status_code=400, detail="Missing query")

        result = await usda_service.search_and_import(body.query)
        return result


@router.get("/cache/stats")
async def cache_stats(request: Request):
    """Get cache statistics."""
    usda_service = request.app.state.usda_service
    stats = await usda_service.get_cache_stats()
    return stats


@router.delete("/cache")
async def clear_cache(request: Request, older_than_days: int = Query(None)):
    """Clear the USDA cache (optionally only entries older than N days)."""
    usda_service = request.app.state.usda_service
    count = await usda_service.clear_cache(older_than_days)
    return {"cleared": count}
