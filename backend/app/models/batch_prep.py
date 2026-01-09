"""Batch prep models for heavy compute endpoint."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BatchPrepIngredient(BaseModel):
    """An aggregated ingredient for batch prep."""

    ingredient_id: str
    ingredient_name: str
    ingredient_kind: str  # "ingredient", "product"

    # Total amount across all servings
    total_amount_g: float

    # Per-serving breakdown
    per_serving_g: float
    servings: int  # Number of meal servings using this ingredient

    # Which meals use this ingredient
    source_meal_ids: list[str] = Field(default_factory=list)
    source_meal_names: list[str] = Field(default_factory=list)

    # Nutrition per 100g (for reference)
    calories_per_100g: float = 0
    protein_g_per_100g: float = 0
    carbs_g_per_100g: float = 0
    fat_g_per_100g: float = 0


class GroupedMeal(BaseModel):
    """A unique meal grouped with its count for batch prep."""

    food_item_id: str
    food_item_name: str
    food_item_kind: str  # "meal", "snack"

    # How many times this meal appears in the batch prep
    count: int

    # Which plan entries this represents
    plan_entry_ids: list[str] = Field(default_factory=list)

    # Single-serving prep instructions (standard recipe steps)
    single_serving_steps: list[str] = Field(default_factory=list)

    # AI-generated or saved batch prep instructions (from recipe_node)
    batch_prep_instructions: Optional[str] = None

    # Recipe timing
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None

    # Ingredients for ONE serving of this meal
    single_serving_ingredients: list[BatchPrepIngredient] = Field(default_factory=list)

    # Ingredients for ALL servings (scaled by count)
    batch_ingredients: list[BatchPrepIngredient] = Field(default_factory=list)

    # Nutrition for one serving
    calories_per_serving: float = 0
    protein_g_per_serving: float = 0
    carbs_g_per_serving: float = 0
    fat_g_per_serving: float = 0


class BatchPrepComputeRequest(BaseModel):
    """Request to compute batch prep data."""

    user_id: str

    # Plan entry IDs to batch prep
    plan_entry_ids: list[str]

    # Optional: Include AI instructions for each recipe
    include_batch_instructions: bool = True


class BatchPrepComputeResponse(BaseModel):
    """Response with organized batch prep data."""

    # Unique meals grouped with their counts
    grouped_meals: list[GroupedMeal] = Field(default_factory=list)

    # Total meals (sum of all counts)
    total_meal_count: int = 0

    # Unique meal count
    unique_meal_count: int = 0

    # Aggregated ingredients across ALL meals
    aggregated_ingredients: list[BatchPrepIngredient] = Field(default_factory=list)

    # Total estimated time
    total_prep_time_minutes: int = 0
    total_cook_time_minutes: int = 0

    # Total nutrition for entire batch
    total_calories: float = 0
    total_protein_g: float = 0
    total_carbs_g: float = 0
    total_fat_g: float = 0
