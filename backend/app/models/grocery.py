"""Grocery list Pydantic models."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GroceryCategory(str, Enum):
    """Grocery item categories for organization."""

    PRODUCE = "produce"
    MEAT_SEAFOOD = "meat_seafood"
    DAIRY = "dairy"
    BAKERY = "bakery"
    FROZEN = "frozen"
    PANTRY = "pantry"
    BEVERAGES = "beverages"
    SNACKS = "snacks"
    CONDIMENTS = "condiments"
    SUPPLEMENTS = "supplements"
    HOUSEHOLD = "household"
    OTHER = "other"


class GroceryItem(BaseModel):
    """A single item on the grocery list."""

    # Identification
    ingredient_id: Optional[str] = None
    canonical_id: Optional[str] = None
    name: str

    # Amounts
    needed_g: float = 0  # Total needed for plan period
    in_stock_g: float = 0  # Current inventory
    to_buy_g: float = 0  # Amount to purchase

    # Display
    display_amount: str = ""  # "500g" or "2 cups"
    display_unit: str = "g"

    # Categorization
    category: GroceryCategory = GroceryCategory.OTHER
    aisle: Optional[str] = None

    # Source breakdown
    from_meals: float = 0  # Amount from meal plan
    from_reorders: float = 0  # Amount from reorder schedules
    from_supplements: float = 0  # Amount from supplements

    # Which meals need this
    meal_sources: list[str] = Field(default_factory=list)

    # Metadata
    notes: Optional[str] = None
    priority: int = 0  # Higher = more important
    checked: bool = False

    # Price estimate (if available)
    estimated_price: Optional[float] = None
    price_per_unit: Optional[float] = None
    unit_for_price: Optional[str] = None


class GroceryList(BaseModel):
    """Complete grocery list for a date range."""

    # Date range
    start_date: date
    end_date: date
    days: int = 0

    # Items
    items: list[GroceryItem] = Field(default_factory=list)
    items_count: int = 0
    items_to_buy_count: int = 0

    # Organized by category
    by_category: dict[str, list[GroceryItem]] = Field(default_factory=dict)

    # Summary
    total_items_needed: int = 0
    items_in_stock: int = 0
    items_to_purchase: int = 0

    # Price estimate
    estimated_total_price: Optional[float] = None

    # For household
    user_ids: list[str] = Field(default_factory=list)
    is_household_list: bool = False

    # Generation info
    meals_included: int = 0
    reorders_included: int = 0
    supplements_included: int = 0


class GroceryGenerationRequest(BaseModel):
    """Request to generate a grocery list."""

    user_id: str
    start_date: date
    end_date: date

    # Sources to include
    include_meals: bool = True
    include_reorders: bool = True
    include_supplements: bool = True

    # Inventory
    subtract_inventory: bool = True

    # Household
    include_household: bool = False
    household_user_ids: Optional[list[str]] = None

    # Grouping
    group_by_category: bool = True
    group_similar_items: bool = True  # "ground beef 80/20" + "ground beef 90/10" -> "ground beef"

    # Thresholds
    minimum_amount_g: float = 10  # Don't include items under this threshold


class StoreRun(BaseModel):
    """A planned store run with optimized list."""

    store_name: str
    store_id: Optional[str] = None

    items: list[GroceryItem] = Field(default_factory=list)
    items_count: int = 0

    # Route optimization (if store layout known)
    aisles_in_order: list[str] = Field(default_factory=list)
    items_by_aisle: dict[str, list[GroceryItem]] = Field(default_factory=dict)

    estimated_total: Optional[float] = None
    estimated_time_minutes: Optional[int] = None


class GroceryOptimizationResult(BaseModel):
    """Result of optimizing grocery across multiple stores."""

    # Which items to get where
    store_runs: list[StoreRun] = Field(default_factory=list)

    # Items not available at any store
    unavailable_items: list[GroceryItem] = Field(default_factory=list)

    # Cost optimization
    total_estimated_cost: Optional[float] = None
    savings_vs_single_store: Optional[float] = None
