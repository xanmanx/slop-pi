"""Nutrition-related Pydantic models with comprehensive micronutrient tracking."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Macros(BaseModel):
    """Macronutrient totals."""

    calories: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0
    saturated_fat_g: float = 0
    cholesterol_mg: float = 0


class NutrientCategory(str, Enum):
    """Categories of nutrients for organization."""

    VITAMIN = "vitamin"
    MINERAL = "mineral"
    AMINO_ACID = "amino_acid"
    FATTY_ACID = "fatty_acid"
    OTHER = "other"


class Micronutrient(BaseModel):
    """A single micronutrient value."""

    nutrient_id: int
    name: str
    amount: float  # In native unit
    unit: str  # mg, µg, IU, etc.
    amount_mg: Optional[float] = None  # Normalized to mg for comparison
    category: NutrientCategory = NutrientCategory.OTHER


class MicronutrientWithRDA(Micronutrient):
    """Micronutrient with RDA (Recommended Daily Allowance) tracking."""

    rda: Optional[float] = None  # Recommended daily amount
    rda_unit: Optional[str] = None
    percent_rda: Optional[float] = None  # Percentage of RDA met
    status: Optional[str] = None  # "deficient", "adequate", "excess"

    @classmethod
    def from_micronutrient(
        cls, micro: Micronutrient, rda: Optional[float] = None, rda_unit: Optional[str] = None
    ) -> MicronutrientWithRDA:
        """Create from a Micronutrient with RDA info."""
        percent = None
        status = None

        if rda and rda > 0:
            # Convert to same unit if needed
            amount_for_comparison = micro.amount
            if micro.unit != rda_unit:
                amount_for_comparison = _convert_units(micro.amount, micro.unit, rda_unit or micro.unit)

            percent = (amount_for_comparison / rda) * 100 if amount_for_comparison else 0

            if percent < 50:
                status = "deficient"
            elif percent < 100:
                status = "low"
            elif percent <= 200:
                status = "adequate"
            else:
                status = "excess"

        return cls(
            nutrient_id=micro.nutrient_id,
            name=micro.name,
            amount=micro.amount,
            unit=micro.unit,
            amount_mg=micro.amount_mg,
            category=micro.category,
            rda=rda,
            rda_unit=rda_unit,
            percent_rda=percent,
            status=status,
        )


def _convert_units(amount: float, from_unit: str, to_unit: str) -> float:
    """Convert between nutrient units."""
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    if from_unit == to_unit:
        return amount

    # Convert to mg first
    mg_value = amount
    if from_unit in ("µg", "ug", "mcg"):
        mg_value = amount / 1000
    elif from_unit == "g":
        mg_value = amount * 1000

    # Convert from mg to target
    if to_unit in ("µg", "ug", "mcg"):
        return mg_value * 1000
    elif to_unit == "g":
        return mg_value / 1000
    else:
        return mg_value


class NutritionSummary(BaseModel):
    """Complete nutrition summary for a meal or day."""

    macros: Macros
    micronutrients: list[MicronutrientWithRDA] = Field(default_factory=list)
    total_grams: float = 0
    item_count: int = 0

    # Quick access to key vitamins/minerals
    vitamin_a_mcg: float = 0
    vitamin_c_mg: float = 0
    vitamin_d_mcg: float = 0
    vitamin_e_mg: float = 0
    vitamin_k_mcg: float = 0
    vitamin_b12_mcg: float = 0
    folate_mcg: float = 0
    calcium_mg: float = 0
    iron_mg: float = 0
    magnesium_mg: float = 0
    potassium_mg: float = 0
    zinc_mg: float = 0
    selenium_mcg: float = 0
    caffeine_mg: float = 0


class DailyNutritionStats(BaseModel):
    """Daily nutrition statistics with RDA comparison."""

    date: date
    nutrition: NutritionSummary
    target_calories: Optional[float] = None
    calories_variance: Optional[float] = None  # Actual - Target
    meals_logged: int = 0
    supplements_logged: int = 0

    # RDA achievement scores (0-100+)
    vitamin_score: float = 0  # Average % RDA for vitamins
    mineral_score: float = 0  # Average % RDA for minerals
    overall_nutrition_score: float = 0  # Weighted average


class NutritionTrend(BaseModel):
    """Trend data for a single nutrient over time."""

    nutrient_name: str
    nutrient_id: Optional[int] = None
    values: list[tuple[str, float]]  # (date, value) pairs
    average: float = 0
    min_value: float = 0
    max_value: float = 0
    trend_direction: str = "stable"  # "increasing", "decreasing", "stable"
    percent_change: float = 0  # Change from first to second half


class NutritionAnalytics(BaseModel):
    """Comprehensive nutrition analytics over a date range."""

    start_date: date
    end_date: date
    days_analyzed: int = 0

    # Aggregated stats
    daily_stats: list[DailyNutritionStats] = Field(default_factory=list)
    average_daily: NutritionSummary
    total_nutrition: NutritionSummary

    # Trends
    calorie_trend: NutritionTrend
    protein_trend: NutritionTrend
    top_nutrients: list[MicronutrientWithRDA] = Field(default_factory=list)
    deficient_nutrients: list[MicronutrientWithRDA] = Field(default_factory=list)

    # Scores
    average_nutrition_score: float = 0
    consistency_score: float = 0  # How consistent daily intake is


# RDA Reference Data (for adults, can be customized per user)
# Source: NIH Office of Dietary Supplements
RDA_REFERENCE = {
    # Vitamins
    1106: {"name": "Vitamin A", "rda": 900, "unit": "µg", "category": "vitamin"},  # RAE
    1162: {"name": "Vitamin C", "rda": 90, "unit": "mg", "category": "vitamin"},
    1114: {"name": "Vitamin D", "rda": 20, "unit": "µg", "category": "vitamin"},
    1109: {"name": "Vitamin E", "rda": 15, "unit": "mg", "category": "vitamin"},
    1185: {"name": "Vitamin K", "rda": 120, "unit": "µg", "category": "vitamin"},
    1165: {"name": "Thiamin (B1)", "rda": 1.2, "unit": "mg", "category": "vitamin"},
    1166: {"name": "Riboflavin (B2)", "rda": 1.3, "unit": "mg", "category": "vitamin"},
    1167: {"name": "Niacin (B3)", "rda": 16, "unit": "mg", "category": "vitamin"},
    1170: {"name": "Pantothenic Acid (B5)", "rda": 5, "unit": "mg", "category": "vitamin"},
    1175: {"name": "Vitamin B6", "rda": 1.3, "unit": "mg", "category": "vitamin"},
    1178: {"name": "Vitamin B12", "rda": 2.4, "unit": "µg", "category": "vitamin"},
    1177: {"name": "Folate", "rda": 400, "unit": "µg", "category": "vitamin"},
    1180: {"name": "Choline", "rda": 550, "unit": "mg", "category": "vitamin"},
    # Minerals
    1087: {"name": "Calcium", "rda": 1000, "unit": "mg", "category": "mineral"},
    1089: {"name": "Iron", "rda": 8, "unit": "mg", "category": "mineral"},  # 18 for women
    1090: {"name": "Magnesium", "rda": 400, "unit": "mg", "category": "mineral"},
    1091: {"name": "Phosphorus", "rda": 700, "unit": "mg", "category": "mineral"},
    1092: {"name": "Potassium", "rda": 2600, "unit": "mg", "category": "mineral"},
    1093: {"name": "Sodium", "rda": 2300, "unit": "mg", "category": "mineral"},  # Upper limit
    1095: {"name": "Zinc", "rda": 11, "unit": "mg", "category": "mineral"},
    1098: {"name": "Copper", "rda": 0.9, "unit": "mg", "category": "mineral"},
    1101: {"name": "Manganese", "rda": 2.3, "unit": "mg", "category": "mineral"},
    1103: {"name": "Selenium", "rda": 55, "unit": "µg", "category": "mineral"},
    # Other
    1079: {"name": "Fiber", "rda": 28, "unit": "g", "category": "other"},
    1057: {"name": "Caffeine", "rda": 400, "unit": "mg", "category": "other"},  # Upper limit
}


def get_rda_info(nutrient_id: int) -> Optional[dict]:
    """Get RDA reference info for a nutrient."""
    return RDA_REFERENCE.get(nutrient_id)


def categorize_nutrient(name: str, nutrient_id: Optional[int] = None) -> NutrientCategory:
    """Categorize a nutrient by name or ID."""
    name_lower = name.lower()

    if nutrient_id and nutrient_id in RDA_REFERENCE:
        cat = RDA_REFERENCE[nutrient_id].get("category", "other")
        return NutrientCategory(cat)

    if "vitamin" in name_lower:
        return NutrientCategory.VITAMIN
    if any(m in name_lower for m in [
        "calcium", "iron", "magnesium", "phosphorus", "potassium",
        "sodium", "zinc", "copper", "manganese", "selenium", "iodine"
    ]):
        return NutrientCategory.MINERAL
    if "amino" in name_lower or any(aa in name_lower for aa in [
        "leucine", "isoleucine", "valine", "lysine", "methionine",
        "phenylalanine", "threonine", "tryptophan", "histidine"
    ]):
        return NutrientCategory.AMINO_ACID
    if "fatty" in name_lower or "omega" in name_lower or "dha" in name_lower or "epa" in name_lower:
        return NutrientCategory.FATTY_ACID

    return NutrientCategory.OTHER
