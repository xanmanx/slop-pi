"""Pydantic models for slop-pi API."""

from .nutrition import (
    Macros,
    Micronutrient,
    MicronutrientWithRDA,
    NutritionSummary,
    DailyNutritionStats,
    NutritionTrend,
    NutritionAnalytics,
)
from .recipes import (
    FlattenedIngredient,
    RecipeNutrition,
    RecipeFlattened,
    RecipeRequest,
)
from .planning import (
    PlanEntry,
    PlanSlot,
    PlanGenerationRequest,
    PlanGenerationResult,
    MealCandidate,
)
from .grocery import (
    GroceryItem,
    GroceryList,
    GroceryGenerationRequest,
)

__all__ = [
    # Nutrition
    "Macros",
    "Micronutrient",
    "MicronutrientWithRDA",
    "NutritionSummary",
    "DailyNutritionStats",
    "NutritionTrend",
    "NutritionAnalytics",
    # Recipes
    "FlattenedIngredient",
    "RecipeNutrition",
    "RecipeFlattened",
    "RecipeRequest",
    # Planning
    "PlanEntry",
    "PlanSlot",
    "PlanGenerationRequest",
    "PlanGenerationResult",
    "MealCandidate",
    # Grocery
    "GroceryItem",
    "GroceryList",
    "GroceryGenerationRequest",
]
