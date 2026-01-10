"""Price tracking models for food cost analysis."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Literal
from decimal import Decimal

from pydantic import BaseModel, Field


class PriceEntry(BaseModel):
    """A single price record."""

    id: Optional[str] = None
    user_id: str
    food_item_id: str
    food_item_name: Optional[str] = None
    price: Decimal
    price_per_100g: Optional[Decimal] = None
    quantity_g: Optional[Decimal] = None
    store_name: Optional[str] = None
    receipt_id: Optional[str] = None
    source: Literal["manual", "receipt", "barcode"] = "manual"
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class PriceRecordRequest(BaseModel):
    """Request to record a price."""

    food_item_id: str
    price: Decimal
    quantity_g: Optional[Decimal] = None
    store_name: Optional[str] = None
    purchase_date: Optional[date] = None


class PriceRecordResponse(BaseModel):
    """Response after recording a price."""

    success: bool
    price_id: Optional[str] = None
    price_per_100g: Optional[Decimal] = None
    is_lowest_price: bool = False
    previous_lowest: Optional[Decimal] = None
    error: Optional[str] = None


class PriceHistory(BaseModel):
    """Price history for a food item."""

    food_item_id: str
    food_item_name: str
    entries: list[PriceEntry] = Field(default_factory=list)
    lowest_price: Optional[Decimal] = None
    lowest_price_store: Optional[str] = None
    highest_price: Optional[Decimal] = None
    average_price: Optional[Decimal] = None
    price_count: int = 0


class PriceTrend(BaseModel):
    """Price trend analysis."""

    food_item_id: str
    food_item_name: str
    trend_direction: Literal["up", "down", "stable"]
    trend_percent: float = 0
    confidence: float = 0
    current_price: Optional[Decimal] = None
    price_30_days_ago: Optional[Decimal] = None
    predicted_next_price: Optional[Decimal] = None
    data_points: int = 0


class PriceComparison(BaseModel):
    """Price comparison across stores."""

    food_item_id: str
    food_item_name: str
    stores: list[StorePrice] = Field(default_factory=list)
    best_value_store: Optional[str] = None
    potential_savings: Optional[Decimal] = None


class StorePrice(BaseModel):
    """Price at a specific store."""

    store_name: str
    latest_price: Decimal
    price_per_100g: Optional[Decimal] = None
    last_seen: datetime
    price_count: int = 1


class PriceAlert(BaseModel):
    """Price drop alert."""

    id: Optional[str] = None
    food_item_id: str
    food_item_name: str
    store_name: str
    current_price: Decimal
    previous_price: Decimal
    drop_percent: float
    recorded_at: datetime


class PriceAlertsResponse(BaseModel):
    """Response for price alerts."""

    alerts: list[PriceAlert] = Field(default_factory=list)
    alert_count: int = 0


class PriceStatsResponse(BaseModel):
    """Price tracking statistics."""

    total_prices_recorded: int = 0
    unique_items_tracked: int = 0
    unique_stores: int = 0
    average_savings_percent: float = 0
    total_potential_savings: Decimal = Decimal("0")
    most_expensive_category: Optional[str] = None
    best_value_store: Optional[str] = None
