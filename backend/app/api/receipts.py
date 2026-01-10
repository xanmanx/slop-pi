"""Receipt OCR API endpoints."""

import base64
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional
from pydantic import BaseModel

from app.models.receipts import (
    ReceiptScanRequest,
    ReceiptScanResponse,
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
    ReceiptHistoryResponse,
    ReceiptStats,
    ParsedReceipt,
    ReceiptLineItem,
    ResolutionStatus,
)
from app.services.receipts import get_receipt_service
from app.services.resolution import get_resolution_service

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


# =============================================================================
# Request/Response models for resolution endpoints
# =============================================================================


class ManualResolutionRequest(BaseModel):
    """Request to manually resolve a line item."""

    food_item_id: Optional[str] = None  # Link to existing food item
    create_new: bool = False  # Create new food item
    new_item_name: Optional[str] = None  # Name for new item
    new_item_barcode: Optional[str] = None  # Barcode for new item
    quantity_g: Optional[float] = None  # Quantity in grams
    skip: bool = False  # Skip this item


class ResolutionStatusResponse(BaseModel):
    """Response with resolution status summary."""

    receipt_id: str
    total_items: int
    resolved: int
    unresolved: int
    resolution_rate: float
    unresolved_items: list[ReceiptLineItem]


@router.post("/scan", response_model=ReceiptScanResponse)
async def scan_receipt(
    body: ReceiptScanRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Scan a receipt image using Google Document AI.

    Extracts store info, line items, prices, and totals.
    Optionally auto-matches items to existing food database.
    Runs resolution chain (barcode extraction, Open Food Facts lookup)
    for unmatched items.

    Requires Google Document AI credentials to be configured.
    """
    receipt_service = get_receipt_service()

    if not receipt_service.is_enabled:
        raise HTTPException(
            status_code=503,
            detail="Receipt OCR is not configured. Set Google Document AI credentials."
        )

    try:
        image_bytes = base64.b64decode(body.image_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")

    result = await receipt_service.scan_receipt(
        image_bytes=image_bytes,
        mime_type=body.mime_type,
        user_id=user_id,
        auto_match=body.auto_match,
        auto_resolve=body.auto_resolve,
    )

    return result


@router.get("/{receipt_id}", response_model=ParsedReceipt)
async def get_receipt(
    receipt_id: str,
    user_id: str = Query(..., description="User ID"),
):
    """Get a specific receipt by ID."""
    receipt_service = get_receipt_service()

    receipt = await receipt_service.get_receipt(receipt_id, user_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return receipt


@router.post("/{receipt_id}/confirm", response_model=ReceiptConfirmResponse)
async def confirm_receipt(
    receipt_id: str,
    body: ReceiptConfirmRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Confirm and import receipt items to inventory.

    Primary workflow:
    1. Scan receipt → get matched items
    2. User confirms/corrects matches
    3. Items added to inventory with auto-calculated expiration dates

    Features:
    - Auto-adds to inventory (default: True)
    - Records prices for price tracking
    - Auto-calculates expiration based on food category + storage type
    - Override expiration per item if needed
    """
    receipt_service = get_receipt_service()

    result = await receipt_service.confirm_receipt(
        receipt_id=receipt_id,
        user_id=user_id,
        confirmed_items=body.confirmed_items,
        add_to_inventory=body.add_to_inventory,
        record_prices=body.record_prices,
        default_storage_type=body.default_storage_type,
    )

    return result


@router.get("/", response_model=ReceiptHistoryResponse)
async def get_receipt_history(
    user_id: str = Query(..., description="User ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get user's receipt history."""
    receipt_service = get_receipt_service()

    receipts = await receipt_service.get_receipt_history(user_id, limit, offset)

    return ReceiptHistoryResponse(
        total=len(receipts),  # TODO: Get actual total count
        receipts=receipts,
    )


@router.delete("/{receipt_id}")
async def delete_receipt(
    receipt_id: str,
    user_id: str = Query(..., description="User ID"),
):
    """Delete a receipt."""
    receipt_service = get_receipt_service()

    deleted = await receipt_service.delete_receipt(receipt_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {"success": True}


@router.get("/stats/summary", response_model=ReceiptStats)
async def get_receipt_stats(
    user_id: str = Query(..., description="User ID"),
):
    """Get receipt scanning statistics."""
    receipt_service = get_receipt_service()

    return await receipt_service.get_stats(user_id)


@router.get("/status/enabled")
async def check_receipt_ocr_status():
    """Check if receipt OCR is enabled and configured."""
    receipt_service = get_receipt_service()

    return {
        "enabled": receipt_service.is_enabled,
        "message": "Receipt OCR is available" if receipt_service.is_enabled else "Receipt OCR is not configured",
    }


# =============================================================================
# Resolution endpoints
# =============================================================================


@router.get("/{receipt_id}/unresolved", response_model=ResolutionStatusResponse)
async def get_unresolved_items(
    receipt_id: str,
    user_id: str = Query(..., description="User ID"),
):
    """
    Get all unresolved items from a receipt that need manual entry.

    Returns items that couldn't be matched via fuzzy search or barcode lookup,
    along with helpful context for manual resolution.
    """
    receipt_service = get_receipt_service()
    resolution_service = get_resolution_service()

    receipt = await receipt_service.get_receipt(receipt_id, user_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Filter to unresolved items
    unresolved_items = [
        item for item in receipt.line_items
        if item.needs_manual_entry or item.resolution_status == ResolutionStatus.UNRESOLVED
    ]

    # Calculate stats
    total = len(receipt.line_items)
    resolved = sum(
        1 for item in receipt.line_items
        if item.resolution_status in (
            ResolutionStatus.FUZZY_MATCHED,
            ResolutionStatus.BARCODE_MATCHED,
            ResolutionStatus.MANUAL_ENTRY,
        )
    )

    return ResolutionStatusResponse(
        receipt_id=receipt_id,
        total_items=total,
        resolved=resolved,
        unresolved=len(unresolved_items),
        resolution_rate=resolved / total if total > 0 else 0.0,
        unresolved_items=unresolved_items,
    )


@router.post("/{receipt_id}/items/{item_index}/scan-barcode", response_model=ReceiptLineItem)
async def scan_barcode_for_item(
    receipt_id: str,
    item_index: int,
    barcode: str = Query(..., description="Scanned barcode"),
    user_id: str = Query(..., description="User ID"),
):
    """
    Resolve a receipt line item by scanning its barcode.

    Use this when automatic extraction failed but user can scan the product.
    Looks up the barcode in Open Food Facts.
    """
    receipt_service = get_receipt_service()
    resolution_service = get_resolution_service()

    receipt = await receipt_service.get_receipt(receipt_id, user_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if item_index < 0 or item_index >= len(receipt.line_items):
        raise HTTPException(status_code=400, detail="Invalid item index")

    line_item = receipt.line_items[item_index]

    # Try to resolve with scanned barcode
    resolved_item = await resolution_service.resolve_with_scanned_barcode(
        line_item=line_item,
        barcode=barcode,
    )

    # Update in database
    from app.services.supabase import get_supabase_client
    import json

    client = get_supabase_client()

    # Get the line item ID from database
    items_result = client.table("receipt_line_items").select("id").eq(
        "receipt_id", receipt_id
    ).execute()

    if items_result.data and item_index < len(items_result.data):
        item_id = items_result.data[item_index]["id"]

        # Serialize extracted codes
        extracted_codes_json = [
            {
                "code": code.code,
                "code_type": code.code_type.value,
                "confidence": code.confidence,
                "source_text": code.source_text,
            }
            for code in (resolved_item.extracted_codes or [])
        ]

        # Update the line item
        client.table("receipt_line_items").update({
            "resolution_status": resolved_item.resolution_status.value,
            "resolution_method": resolved_item.resolution_method,
            "scanned_barcode": resolved_item.scanned_barcode,
            "off_product_name": resolved_item.off_product_name,
            "off_brand": resolved_item.off_brand,
            "off_barcode": resolved_item.off_barcode,
            "needs_manual_entry": resolved_item.needs_manual_entry,
            "match_confidence": resolved_item.match_confidence,
            "extracted_codes": json.dumps(extracted_codes_json),
        }).eq("id", item_id).execute()

    return resolved_item


@router.post("/{receipt_id}/items/{item_index}/resolve-manual", response_model=ReceiptLineItem)
async def resolve_manual(
    receipt_id: str,
    item_index: int,
    body: ManualResolutionRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Manually resolve a line item by linking to food_item or creating new.

    This is the final fallback in the resolution chain when automatic
    matching and barcode scanning both fail.
    """
    from app.services.supabase import get_supabase_client, TABLES

    receipt_service = get_receipt_service()

    receipt = await receipt_service.get_receipt(receipt_id, user_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if item_index < 0 or item_index >= len(receipt.line_items):
        raise HTTPException(status_code=400, detail="Invalid item index")

    line_item = receipt.line_items[item_index]
    client = get_supabase_client()

    # Handle skip
    if body.skip:
        line_item.resolution_status = ResolutionStatus.SKIPPED
        line_item.needs_manual_entry = False
    elif body.create_new and body.new_item_name:
        # Create new food item
        new_item_data = {
            "user_id": user_id,
            "name": body.new_item_name,
            "kind": "ingredient",
        }
        if body.new_item_barcode:
            new_item_data["barcode"] = body.new_item_barcode

        result = client.table(TABLES["items"]).insert(new_item_data).execute()
        if result.data:
            food_item_id = result.data[0]["id"]
            line_item.food_item_id = food_item_id
            line_item.food_item_name = body.new_item_name
            line_item.is_matched = True
            line_item.resolution_status = ResolutionStatus.MANUAL_ENTRY
            line_item.resolution_method = "manual_new"
            line_item.needs_manual_entry = False
    elif body.food_item_id:
        # Link to existing food item
        line_item.food_item_id = body.food_item_id
        line_item.is_matched = True
        line_item.resolution_status = ResolutionStatus.MANUAL_ENTRY
        line_item.resolution_method = "manual_link"
        line_item.needs_manual_entry = False

        # Get food item name
        food_result = client.table(TABLES["items"]).select("name").eq(
            "id", body.food_item_id
        ).single().execute()
        if food_result.data:
            line_item.food_item_name = food_result.data["name"]
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide food_item_id, create_new with new_item_name, or skip=true"
        )

    # Update in database
    items_result = client.table("receipt_line_items").select("id").eq(
        "receipt_id", receipt_id
    ).execute()

    if items_result.data and item_index < len(items_result.data):
        item_id = items_result.data[item_index]["id"]

        client.table("receipt_line_items").update({
            "food_item_id": line_item.food_item_id,
            "resolution_status": line_item.resolution_status.value,
            "resolution_method": line_item.resolution_method,
            "needs_manual_entry": line_item.needs_manual_entry,
            "match_confidence": 1.0 if line_item.is_matched else None,
        }).eq("id", item_id).execute()

    return line_item


@router.post("/{receipt_id}/retry-resolution", response_model=ReceiptScanResponse)
async def retry_resolution(
    receipt_id: str,
    user_id: str = Query(..., description="User ID"),
    item_indices: Optional[list[int]] = Body(None, description="Specific item indices to retry"),
):
    """
    Retry resolution for all or specific unresolved items.

    Useful after Open Food Facts database updates or cache refresh.
    """
    receipt_service = get_receipt_service()
    resolution_service = get_resolution_service()

    receipt = await receipt_service.get_receipt(receipt_id, user_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Filter to items to retry
    if item_indices:
        items_to_retry = [
            receipt.line_items[i] for i in item_indices
            if 0 <= i < len(receipt.line_items)
        ]
    else:
        items_to_retry = [
            item for item in receipt.line_items
            if item.resolution_status in (ResolutionStatus.PENDING, ResolutionStatus.UNRESOLVED)
        ]

    # Reset status for retry
    for item in items_to_retry:
        item.resolution_status = ResolutionStatus.PENDING
        item.is_matched = False

    # Re-run resolution
    receipt = await resolution_service.batch_resolve(receipt, user_id)

    # Update items in database
    from app.services.supabase import get_supabase_client
    import json

    client = get_supabase_client()
    items_result = client.table("receipt_line_items").select("id").eq(
        "receipt_id", receipt_id
    ).execute()

    for i, item in enumerate(receipt.line_items):
        if items_result.data and i < len(items_result.data):
            item_id = items_result.data[i]["id"]

            extracted_codes_json = [
                {
                    "code": code.code,
                    "code_type": code.code_type.value,
                    "confidence": code.confidence,
                    "source_text": code.source_text,
                }
                for code in (item.extracted_codes or [])
            ]

            client.table("receipt_line_items").update({
                "resolution_status": item.resolution_status.value,
                "resolution_method": item.resolution_method,
                "extracted_codes": json.dumps(extracted_codes_json),
                "off_product_name": item.off_product_name,
                "off_brand": item.off_brand,
                "off_barcode": item.off_barcode,
                "needs_manual_entry": item.needs_manual_entry,
                "manual_entry_hint": item.manual_entry_hint,
                "food_item_id": item.food_item_id,
                "match_confidence": item.match_confidence,
            }).eq("id", item_id).execute()

    # Build response
    summary = resolution_service.get_resolution_summary(receipt)

    return ReceiptScanResponse(
        success=True,
        receipt_id=receipt_id,
        receipt=receipt,
        items_matched=summary["fuzzy_matched"],
        items_unmatched=summary["unresolved"],
        items_barcode_matched=summary["barcode_matched"],
        items_needs_manual=summary["unresolved"],
    )
