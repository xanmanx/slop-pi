"""Receipt OCR API endpoints."""

import base64
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models.receipts import (
    ReceiptScanRequest,
    ReceiptScanResponse,
    ReceiptConfirmRequest,
    ReceiptConfirmResponse,
    ReceiptHistoryResponse,
    ReceiptStats,
    ParsedReceipt,
)
from app.services.receipts import get_receipt_service

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


@router.post("/scan", response_model=ReceiptScanResponse)
async def scan_receipt(
    body: ReceiptScanRequest,
    user_id: str = Query(..., description="User ID"),
):
    """
    Scan a receipt image using Google Document AI.

    Extracts store info, line items, prices, and totals.
    Optionally auto-matches items to existing food database.

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
