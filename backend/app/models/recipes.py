"""Recipe-related Pydantic models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .nutrition import Macros, MicronutrientWithRDA


class FlattenedIngredient(BaseModel):
    """A single ingredient from a flattened recipe."""

    ingredient_id: str
    ingredient_name: str
    ingredient_kind: str  # "ingredient", "product"
    amount_g: float

    # Nutrition per 100g
    calories_per_100g: float = 0
    protein_g_per_100g: float = 0
    carbs_g_per_100g: float = 0
    fat_g_per_100g: float = 0

    # Computed nutrition for this amount
    calories: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0

    # Micronutrients (raw from DB)
    micronutrients: list = Field(default_factory=list)

    # Canonical ingredient reference (if applicable)
    canonical_id: Optional[str] = None
    canonical_name: Optional[str] = None
    is_user_preference: bool = False

    def compute_nutrition(self) -> None:
        """Compute nutrition values based on amount."""
        mult = self.amount_g / 100
        self.calories = self.calories_per_100g * mult
        self.protein_g = self.protein_g_per_100g * mult
        self.carbs_g = self.carbs_g_per_100g * mult
        self.fat_g = self.fat_g_per_100g * mult


class RecipeNutrition(BaseModel):
    """Computed nutrition for a recipe."""

    # Totals
    total_calories: float = 0
    total_protein_g: float = 0
    total_carbs_g: float = 0
    total_fat_g: float = 0
    total_grams: float = 0

    # Per 100g (normalized)
    calories_per_100g: float = 0
    protein_g_per_100g: float = 0
    carbs_g_per_100g: float = 0
    fat_g_per_100g: float = 0

    # Extended macros
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0
    saturated_fat_g: float = 0

    # Top micronutrients (with RDA)
    top_micronutrients: list[MicronutrientWithRDA] = Field(default_factory=list)

    # Scores
    protein_ratio: float = 0  # Protein calories / total calories
    nutrition_density_score: float = 0  # Nutrients per calorie


class RecipeFlattened(BaseModel):
    """Complete flattened recipe with all ingredients and nutrition."""

    recipe_id: str
    recipe_name: str
    recipe_kind: str  # "meal", "snack"

    # Scale factor applied (1.0 = base recipe)
    scale_factor: float = 1.0

    # Flattened ingredients
    ingredients: list[FlattenedIngredient] = Field(default_factory=list)
    ingredient_count: int = 0

    # Computed nutrition
    nutrition: RecipeNutrition

    # Recipe metadata
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    prep_steps: list[str] = Field(default_factory=list)

    # DAG info
    cycle_detected: bool = False
    max_depth: int = 0


class RecipeRequest(BaseModel):
    """Request to flatten a recipe."""

    recipe_id: str
    user_id: str
    scale_factor: float = 1.0
    include_micronutrients: bool = True
    include_rda: bool = True


class BatchRecipeRequest(BaseModel):
    """Request to flatten multiple recipes in parallel."""

    recipe_ids: list[str]
    user_id: str
    scale_factors: Optional[dict[str, float]] = None  # recipe_id -> scale
    include_micronutrients: bool = True


class RecipeComparisonResult(BaseModel):
    """Compare nutrition between multiple recipes."""

    recipes: list[RecipeFlattened]

    # Best for specific goals
    highest_protein: Optional[str] = None
    lowest_calories: Optional[str] = None
    best_nutrition_score: Optional[str] = None

    # Comparison matrix
    comparison_notes: list[str] = Field(default_factory=list)
