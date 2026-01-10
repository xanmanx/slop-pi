"""Receipt OCR models for Google Document AI integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Literal
from decimal import Decimal

from pydantic import BaseModel, Field


class ReceiptLineItem(BaseModel):
    """A single line item from a receipt."""

    id: Optional[str] = None
    raw_text: str
    parsed_name: Optional[str] = None
    quantity: int = 1
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    food_item_id: Optional[str] = None
    food_item_name: Optional[str] = None
    match_confidence: Optional[float] = None
    category: Optional[str] = None
    is_matched: bool = False


class ParsedReceipt(BaseModel):
    """A parsed receipt from OCR."""

    id: Optional[str] = None
    user_id: Optional[str] = None
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    purchase_date: Optional[date] = None
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Optional[Decimal] = None
    payment_method: Optional[str] = None
    line_items: list[ReceiptLineItem] = Field(default_factory=list)
    raw_text: Optional[str] = None
    image_path: Optional[str] = None
    ocr_confidence: Optional[float] = None
    processed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ReceiptScanRequest(BaseModel):
    """Request to scan a receipt image."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    mime_type: str = Field(default="image/jpeg", description="Image MIME type")
    auto_match: bool = Field(default=True, description="Auto-match items to food database")


class ReceiptScanResponse(BaseModel):
    """Response from receipt scanning."""

    success: bool
    receipt_id: Optional[str] = None
    receipt: Optional[ParsedReceipt] = None
    items_matched: int = 0
    items_unmatched: int = 0
    processing_time_ms: float = 0
    error: Optional[str] = None


class ReceiptConfirmRequest(BaseModel):
    """Request to confirm and import receipt items."""

    receipt_id: str
    confirmed_items: list[ReceiptLineItemConfirmation] = Field(default_factory=list)
    add_to_inventory: bool = True  # Primary use case: auto-add to inventory
    record_prices: bool = True
    default_storage_type: Literal["pantry", "refrigerator", "freezer"] = "refrigerator"


class ReceiptLineItemConfirmation(BaseModel):
    """Confirmation/correction for a line item."""

    line_item_index: int
    food_item_id: str
    quantity_g: Optional[float] = None
    unit_price: Optional[Decimal] = None
    storage_type: Optional[Literal["pantry", "refrigerator", "freezer"]] = None  # Override default
    expiration_date: Optional[date] = None  # Override auto-calculated
    skip: bool = False


class ReceiptConfirmResponse(BaseModel):
    """Response after confirming receipt items."""

    success: bool
    receipt_id: str
    items_imported: int = 0
    prices_recorded: int = 0
    inventory_updated: int = 0
    error: Optional[str] = None


class ReceiptHistoryResponse(BaseModel):
    """Response for receipt history."""

    total: int
    receipts: list[ParsedReceipt] = Field(default_factory=list)


class ReceiptStats(BaseModel):
    """Receipt scanning statistics."""

    total_receipts: int = 0
    total_items_scanned: int = 0
    total_items_matched: int = 0
    match_rate: float = 0
    total_spent: Decimal = Decimal("0")
    receipts_this_month: int = 0
    most_visited_store: Optional[str] = None
