"""Barcode lookup models for Open Food Facts integration."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


class NutritionPer100g(BaseModel):
    """Nutrition facts per 100g from barcode lookup."""

    calories: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0
    saturated_fat_g: float = 0


class ProductInfo(BaseModel):
    """Product information from barcode lookup."""

    barcode: str
    name: str
    brand: Optional[str] = None
    quantity: Optional[str] = None  # e.g., "500g", "1L", "12 oz"
    serving_size: Optional[str] = None
    serving_size_g: Optional[float] = None
    categories: list[str] = Field(default_factory=list)
    nutrition_per_100g: NutritionPer100g = Field(default_factory=NutritionPer100g)
    ingredients_text: Optional[str] = None
    allergens: list[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    image_thumb_url: Optional[str] = None
    nutriscore_grade: Optional[str] = None  # a, b, c, d, e
    nova_group: Optional[int] = None  # 1-4 (food processing level)
    ecoscore_grade: Optional[str] = None
    source: Literal["cache", "api"] = "api"
    cached_at: Optional[datetime] = None


class BarcodeNotFound(BaseModel):
    """Response when barcode is not found."""

    barcode: str
    found: bool = False
    message: str = "Product not found in Open Food Facts database"
    suggestions: list[str] = Field(default_factory=list)


class BarcodeLookupResponse(BaseModel):
    """Response for barcode lookup endpoint."""

    success: bool
    barcode: str
    product: Optional[ProductInfo] = None
    error: Optional[str] = None
    source: Literal["cache", "api", "not_found"] = "api"
    lookup_time_ms: float = 0


class BatchBarcodeLookupRequest(BaseModel):
    """Request to look up multiple barcodes."""

    barcodes: list[str] = Field(..., min_length=1, max_length=50)


class BatchBarcodeLookupResponse(BaseModel):
    """Response for batch barcode lookup."""

    total_requested: int
    found: int
    not_found: int
    products: list[ProductInfo] = Field(default_factory=list)
    not_found_barcodes: list[str] = Field(default_factory=list)
    lookup_time_ms: float = 0


class BarcodeImportRequest(BaseModel):
    """Request to import barcode product as food item."""

    barcode: str
    override_name: Optional[str] = None
    override_serving_g: Optional[float] = None
    kind: Literal["ingredient", "product", "snack"] = "product"
    add_to_inventory: bool = False
    inventory_quantity_g: Optional[float] = None


class BarcodeImportResponse(BaseModel):
    """Response after importing barcode product."""

    success: bool
    barcode: str
    food_item_id: Optional[str] = None
    food_item_name: Optional[str] = None
    added_to_inventory: bool = False
    inventory_item_id: Optional[str] = None
    error: Optional[str] = None


class BarcodeCacheStats(BaseModel):
    """Statistics about the barcode cache."""

    total_cached: int = 0
    cache_hits_today: int = 0
    cache_size_mb: float = 0
    oldest_entry: Optional[datetime] = None
    newest_entry: Optional[datetime] = None
