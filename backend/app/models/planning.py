"""Meal planning Pydantic models."""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .nutrition import Macros


class PlanSlot(str, Enum):
    """Meal slots in a day."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class PlanEntry(BaseModel):
    """A single planned meal entry."""

    id: Optional[str] = None
    user_id: str
    food_item_id: str
    food_item_name: Optional[str] = None
    food_item_kind: Optional[str] = None

    planned_date: date
    slot: PlanSlot
    time: Optional[time] = None

    scale_factor: float = 1.0  # Servings or grams depending on item kind

    # Computed nutrition
    estimated_calories: float = 0
    estimated_protein_g: float = 0
    estimated_carbs_g: float = 0
    estimated_fat_g: float = 0

    # Status
    is_logged: bool = False
    consumed_at: Optional[str] = None

    # Metadata
    notes: Optional[str] = None
    source: Optional[str] = None  # "generated", "manual", "suggested"


class MealCandidate(BaseModel):
    """A candidate meal for plan generation."""

    food_item_id: str
    name: str
    kind: str
    base_calories: float
    calories_per_100g: Optional[float] = None
    protein_g_per_100g: Optional[float] = None
    carbs_g_per_100g: Optional[float] = None
    fat_g_per_100g: Optional[float] = None

    # Scoring for selection
    frequency_score: float = 0  # How often used recently
    variety_score: float = 0  # Promotes variety
    nutrition_score: float = 0  # Matches target macros
    total_score: float = 0

    # Scaling info
    min_scale: float = 0.25
    max_scale: float = 4.0


class SlotTargets(BaseModel):
    """Calorie/macro targets per slot."""

    breakfast: float = 0
    lunch: float = 0
    dinner: float = 0
    snack: float = 0


class PlanGenerationRequest(BaseModel):
    """Request to generate a meal plan."""

    user_id: str
    start_date: date
    days: int = 7

    # Target overrides (use prefs if not specified)
    daily_calories: Optional[float] = None
    protein_pct: Optional[float] = None
    carbs_pct: Optional[float] = None
    fat_pct: Optional[float] = None

    # Slot configuration
    breakfasts_per_day: int = 1
    lunches_per_day: int = 1
    dinners_per_day: int = 1
    snacks_per_day: int = 2

    # Generation options
    avoid_recent_meals: bool = True  # Don't repeat meals from last N days
    lookback_days: int = 7
    prefer_variety: bool = True
    match_macros: bool = True

    # Meal pools (optional filter)
    allowed_pool_ids: Optional[list[str]] = None

    # For household planning
    include_household_meals: bool = False
    controlled_user_ids: Optional[list[str]] = None


class PlanGenerationResult(BaseModel):
    """Result of plan generation."""

    success: bool
    entries: list[PlanEntry] = Field(default_factory=list)
    entries_created: int = 0

    # Per-day summary
    daily_summaries: list[DaySummary] = Field(default_factory=list)

    # Stats
    total_calories: float = 0
    avg_daily_calories: float = 0
    target_daily_calories: float = 0
    calorie_accuracy_pct: float = 0

    # Issues
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # Timing
    generation_time_ms: float = 0


class DaySummary(BaseModel):
    """Summary for a single day in the plan."""

    date: date
    slots_filled: dict[str, int] = Field(default_factory=dict)

    target_calories: float = 0
    planned_calories: float = 0
    variance_calories: float = 0
    variance_pct: float = 0

    macros: Macros = Field(default_factory=Macros)

    meal_names: list[str] = Field(default_factory=list)


class HouseholdPlanRequest(BaseModel):
    """Request to generate synchronized household plans."""

    controller_user_id: str
    controlled_user_ids: list[str]
    start_date: date
    days: int = 7

    # Shared meals (all eat together)
    shared_slots: list[PlanSlot] = Field(default_factory=lambda: [PlanSlot.DINNER])

    # Per-user calorie targets (computed from prefs if not specified)
    user_calories: Optional[dict[str, float]] = None


class HouseholdPlanResult(BaseModel):
    """Result of household plan generation."""

    success: bool
    plans_by_user: dict[str, PlanGenerationResult] = Field(default_factory=dict)

    # Shared meals
    shared_meal_names: list[str] = Field(default_factory=list)

    # Shopping list hint
    unique_ingredients_count: int = 0
