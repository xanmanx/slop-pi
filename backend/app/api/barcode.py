"""Open Food Facts barcode lookup API endpoints with local SQLite caching."""

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional, Literal

from app.models.barcode import (
    BatchBarcodeLookupRequest,
    BarcodeImportRequest,
)

router = APIRouter(prefix="/api/barcode", tags=["barcode"])


@router.get("/{barcode}")
async def lookup_barcode(
    request: Request,
    barcode: str,
    use_cache: bool = Query(True, description="Use local SQLite cache"),
):
    """
    Look up a product by barcode using Open Food Facts.

    Returns nutrition data, brand, allergens, nutriscore, and more.
    Results are cached locally for instant subsequent lookups.
    """
    barcode_service = request.app.state.barcode_service

    result = await barcode_service.lookup(barcode)

    # If not using cache and we got a cache hit, refetch from API
    if not use_cache and result.source == "cache":
        # Clear this barcode from cache and refetch
        await barcode_service.db.execute(
            "DELETE FROM products WHERE barcode = ?",
            (barcode_service._normalize_barcode(barcode),)
        )
        await barcode_service.db.commit()
        result = await barcode_service.lookup(barcode)

    return result.model_dump()


@router.post("/batch")
async def lookup_batch(
    request: Request,
    body: BatchBarcodeLookupRequest,
):
    """
    Look up multiple barcodes at once.

    Limited to 50 barcodes per request.
    """
    barcode_service = request.app.state.barcode_service

    result = await barcode_service.lookup_batch(body.barcodes)
    return result.model_dump()


class ImportRequest(BaseModel):
    """Request to import barcode product as food item."""
    override_name: Optional[str] = None
    override_serving_g: Optional[float] = None
    kind: Literal["ingredient", "product", "snack"] = "product"
    add_to_inventory: bool = False
    inventory_quantity_g: Optional[float] = None


@router.post("/import/{barcode}")
async def import_barcode(
    request: Request,
    barcode: str,
    body: ImportRequest,
    user_id: str = Query(..., description="User ID to import for"),
):
    """
    Import a barcode product as a food item in Supabase.

    Optionally add to inventory at the same time.
    """
    barcode_service = request.app.state.barcode_service

    result = await barcode_service.import_to_supabase(
        barcode=barcode,
        user_id=user_id,
        override_name=body.override_name,
        override_serving_g=body.override_serving_g,
        kind=body.kind,
        add_to_inventory=body.add_to_inventory,
        inventory_quantity_g=body.inventory_quantity_g,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return result.model_dump()


@router.get("/search/name")
async def search_by_name(
    request: Request,
    query: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
):
    """
    Search cached products by name.

    Only searches local cache - does not hit Open Food Facts API.
    Useful for finding previously scanned products.
    """
    barcode_service = request.app.state.barcode_service

    cursor = await barcode_service.db.execute(
        """SELECT * FROM products
           WHERE name LIKE ? OR brand LIKE ?
           ORDER BY access_count DESC, last_accessed DESC
           LIMIT ?""",
        (f"%{query}%", f"%{query}%", limit)
    )
    rows = await cursor.fetchall()

    products = [barcode_service._row_to_product(row).model_dump() for row in rows]

    return {
        "query": query,
        "count": len(products),
        "products": products,
    }


@router.get("/cache/stats")
async def cache_stats(request: Request):
    """Get barcode cache statistics."""
    barcode_service = request.app.state.barcode_service
    stats = await barcode_service.get_cache_stats()
    return stats.model_dump()


@router.delete("/cache")
async def clear_cache(
    request: Request,
    older_than_days: int = Query(None, description="Only clear entries older than N days"),
):
    """Clear the barcode cache (optionally only entries older than N days)."""
    barcode_service = request.app.state.barcode_service
    await barcode_service.clear_cache(older_than_days)
    return {"cleared": True, "older_than_days": older_than_days}


@router.get("/recent")
async def recent_products(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get recently scanned products.

    Returns products ordered by last access time.
    """
    barcode_service = request.app.state.barcode_service

    cursor = await barcode_service.db.execute(
        """SELECT * FROM products
           ORDER BY last_accessed DESC
           LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()

    products = [barcode_service._row_to_product(row).model_dump() for row in rows]

    return {
        "count": len(products),
        "products": products,
    }


@router.get("/frequent")
async def frequent_products(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get frequently accessed products.

    Returns products ordered by access count.
    """
    barcode_service = request.app.state.barcode_service

    cursor = await barcode_service.db.execute(
        """SELECT * FROM products
           ORDER BY access_count DESC, last_accessed DESC
           LIMIT ?""",
        (limit,)
    )
    rows = await cursor.fetchall()

    products = [barcode_service._row_to_product(row).model_dump() for row in rows]

    return {
        "count": len(products),
        "products": products,
    }
