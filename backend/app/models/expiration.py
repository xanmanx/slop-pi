"""Expiration date management models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


class StorageType(BaseModel):
    """Storage type with shelf life information."""

    name: Literal["pantry", "refrigerator", "freezer"]
    display_name: str
    default_days: Optional[int] = None


class ShelfLifeInfo(BaseModel):
    """Shelf life information for a category/item."""

    category: str
    subcategory: Optional[str] = None
    pantry_days: Optional[int] = None
    refrigerator_days: Optional[int] = None
    freezer_days: Optional[int] = None
    notes: Optional[str] = None
    source: str = "usda_foodkeeper"


class InventoryExpiration(BaseModel):
    """Inventory item with expiration info."""

    inventory_id: str
    food_item_id: str
    food_item_name: str
    food_item_kind: str
    quantity_g: float
    storage_type: Literal["pantry", "refrigerator", "freezer"] = "refrigerator"
    purchase_date: Optional[date] = None
    expiration_date: Optional[date] = None
    days_until_expiry: Optional[int] = None
    status: Literal["fresh", "use_soon", "expiring", "expired"] = "fresh"
    suggested_expiration: Optional[date] = None


class ExpirationSetRequest(BaseModel):
    """Request to set expiration date."""

    inventory_id: str
    expiration_date: Optional[date] = None
    purchase_date: Optional[date] = None
    storage_type: Optional[Literal["pantry", "refrigerator", "freezer"]] = None
    use_suggested: bool = False


class ExpirationSetResponse(BaseModel):
    """Response after setting expiration."""

    success: bool
    inventory_id: str
    expiration_date: Optional[date] = None
    days_until_expiry: Optional[int] = None
    status: str = "fresh"
    error: Optional[str] = None


class ExpiringItemsResponse(BaseModel):
    """Response for items expiring soon."""

    items: list[InventoryExpiration] = Field(default_factory=list)
    expiring_count: int = 0
    expired_count: int = 0
    total_value_at_risk: Optional[float] = None  # Based on price tracking


class ShelfLifeCorrection(BaseModel):
    """User correction for shelf life (for learning)."""

    id: Optional[str] = None
    user_id: str
    food_item_id: str
    category: str
    storage_type: Literal["pantry", "refrigerator", "freezer"]
    expected_days: int
    actual_days: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ShelfLifeCorrectionRequest(BaseModel):
    """Request to record a shelf life correction."""

    food_item_id: str
    storage_type: Literal["pantry", "refrigerator", "freezer"]
    expected_days: int
    actual_days: int
    notes: Optional[str] = None


class ShelfLifeCorrectionResponse(BaseModel):
    """Response after recording correction."""

    success: bool
    correction_id: Optional[str] = None
    updated_estimate: Optional[int] = None
    error: Optional[str] = None


class CategoryDefaultsResponse(BaseModel):
    """Default shelf life for a category."""

    category: str
    pantry_days: Optional[int] = None
    refrigerator_days: Optional[int] = None
    freezer_days: Optional[int] = None
    subcategories: list[ShelfLifeInfo] = Field(default_factory=list)
    source: str = "usda_foodkeeper"


class ExpirationStatsResponse(BaseModel):
    """Expiration tracking statistics."""

    items_with_expiration: int = 0
    items_expiring_this_week: int = 0
    items_expired: int = 0
    average_days_to_expiry: Optional[float] = None
    most_wasted_category: Optional[str] = None
    waste_prevention_score: float = 0  # 0-100
