"""
Comprehensive nutrition calculation service.

Handles all nutrition computations including:
- Macro calculations
- Micronutrient aggregation with RDA tracking
- Daily/weekly/monthly analytics
- Trend analysis
- Nutrition scoring

Optimized for Raspberry Pi: uses numpy for batch operations
and caches aggressively.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

from app.config import get_settings
from app.models.nutrition import (
    Macros,
    Micronutrient,
    MicronutrientWithRDA,
    NutritionSummary,
    DailyNutritionStats,
    NutritionTrend,
    NutritionAnalytics,
    NutrientCategory,
    RDA_REFERENCE,
    get_rda_info,
    categorize_nutrient,
)
from app.services.supabase import get_supabase_client, TABLES
from app.services.recipes import flatten_recipe_auto_owner

logger = logging.getLogger(__name__)
settings = get_settings()

# Thread pool for CPU-intensive calculations
_executor = ThreadPoolExecutor(max_workers=4)


# Nutrient IDs for quick access
NUTRIENT_IDS = {
    "calories": 1008,
    "protein": 1003,
    "fat": 1004,
    "carbs": 1005,
    "fiber": 1079,
    "sugar": 2000,
    "sodium": 1093,
    "saturated_fat": 1258,
    "cholesterol": 1253,
    "vitamin_a": 1106,
    "vitamin_c": 1162,
    "vitamin_d": 1114,
    "vitamin_e": 1109,
    "vitamin_k": 1185,
    "vitamin_b12": 1178,
    "folate": 1177,
    "calcium": 1087,
    "iron": 1089,
    "magnesium": 1090,
    "potassium": 1092,
    "zinc": 1095,
    "selenium": 1103,
    "caffeine": 1057,
}

# Nutrients to exclude from micronutrient aggregation (they're macros)
MACRO_NUTRIENT_IDS = {1008, 1003, 1004, 1005}

# Useless nutrients to filter out
USELESS_NUTRIENTS = {
    "water", "ash", "alcohol, ethyl", "nitrogen",
    "carbohydrate, by summation", "carbohydrate, by difference",
    "energy", "total sugars", "sucrose", "fructose", "glucose",
    "lactose", "maltose", "galactose", "total lipid (fat)",
}


class NutritionService:
    """High-performance nutrition calculation service."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_ttl = 300  # 5 minutes

    # =========================================================================
    # Core Calculation Methods
    # =========================================================================

    def calculate_macros_from_items(
        self,
        items: list[dict],
        amounts_g: list[float],
    ) -> Macros:
        """Calculate total macros from items and amounts (vectorized)."""
        if not items or not amounts_g:
            return Macros()

        total = Macros()

        for item, amount_g in zip(items, amounts_g):
            if not item or amount_g <= 0:
                continue

            mult = amount_g / 100

            total.calories += (item.get("calories_per_100g") or 0) * mult
            total.protein_g += (item.get("protein_g_per_100g") or 0) * mult
            total.carbs_g += (item.get("carbs_g_per_100g") or 0) * mult
            total.fat_g += (item.get("fat_g_per_100g") or 0) * mult

            # Extended macros from micronutrients
            micros = item.get("micronutrients") or []
            for m in micros:
                nid = m.get("nutrient_id")
                per100 = m.get("amount_per_100g") or m.get("amount_mg_per_100g") or 0
                val = per100 * mult

                if nid == NUTRIENT_IDS["fiber"]:
                    total.fiber_g += val
                elif nid == NUTRIENT_IDS["sugar"]:
                    total.sugar_g += val
                elif nid == NUTRIENT_IDS["sodium"]:
                    total.sodium_mg += val
                elif nid == NUTRIENT_IDS["saturated_fat"]:
                    total.saturated_fat_g += val
                elif nid == NUTRIENT_IDS["cholesterol"]:
                    total.cholesterol_mg += val

        return total

    def aggregate_micronutrients(
        self,
        items: list[dict],
        amounts_g: list[float],
        include_rda: bool = True,
        top_n: int = 20,
    ) -> list[MicronutrientWithRDA]:
        """Aggregate micronutrients from multiple items with RDA tracking."""
        if not items or not amounts_g:
            return []

        # Aggregate by nutrient_id
        totals: dict[int, dict] = {}

        for item, amount_g in zip(items, amounts_g):
            if not item or amount_g <= 0:
                continue

            micros = item.get("micronutrients") or []
            mult = amount_g / 100

            for m in micros:
                nid = m.get("nutrient_id")
                if not nid or nid in MACRO_NUTRIENT_IDS:
                    continue

                name = m.get("name", "").strip()
                if not name or name.lower() in USELESS_NUTRIENTS:
                    continue

                per100 = m.get("amount_per_100g") or m.get("amount_mg_per_100g") or 0
                if per100 <= 0:
                    continue

                unit = m.get("unit", "mg")
                amount = per100 * mult
                amount_mg = self._to_mg(amount, unit)

                if nid not in totals:
                    totals[nid] = {
                        "nutrient_id": nid,
                        "name": name,
                        "amount": 0,
                        "unit": unit,
                        "amount_mg": 0,
                        "category": categorize_nutrient(name, nid),
                    }

                totals[nid]["amount"] += amount
                if amount_mg is not None:
                    totals[nid]["amount_mg"] = (totals[nid].get("amount_mg") or 0) + amount_mg

        # Convert to MicronutrientWithRDA
        result = []
        for nid, data in totals.items():
            micro = Micronutrient(
                nutrient_id=nid,
                name=data["name"],
                amount=data["amount"],
                unit=data["unit"],
                amount_mg=data.get("amount_mg"),
                category=data["category"],
            )

            if include_rda:
                rda_info = get_rda_info(nid)
                if rda_info:
                    result.append(MicronutrientWithRDA.from_micronutrient(
                        micro,
                        rda=rda_info["rda"],
                        rda_unit=rda_info["unit"],
                    ))
                else:
                    result.append(MicronutrientWithRDA(
                        nutrient_id=micro.nutrient_id,
                        name=micro.name,
                        amount=micro.amount,
                        unit=micro.unit,
                        amount_mg=micro.amount_mg,
                        category=micro.category,
                    ))
            else:
                result.append(MicronutrientWithRDA(
                    nutrient_id=micro.nutrient_id,
                    name=micro.name,
                    amount=micro.amount,
                    unit=micro.unit,
                    amount_mg=micro.amount_mg,
                    category=micro.category,
                ))

        # Sort by amount_mg (descending), then by RDA % if available
        result.sort(
            key=lambda x: (
                -(x.percent_rda or 0),
                -(x.amount_mg or 0),
            )
        )

        return result[:top_n] if top_n else result

    def create_nutrition_summary(
        self,
        items: list[dict],
        amounts_g: list[float],
        include_rda: bool = True,
    ) -> NutritionSummary:
        """Create a complete nutrition summary from items and amounts."""
        macros = self.calculate_macros_from_items(items, amounts_g)
        micros = self.aggregate_micronutrients(items, amounts_g, include_rda)

        total_grams = sum(a for a in amounts_g if a > 0)

        summary = NutritionSummary(
            macros=macros,
            micronutrients=micros,
            total_grams=total_grams,
            item_count=len([i for i in items if i]),
        )

        # Extract key nutrients
        for m in micros:
            if m.nutrient_id == NUTRIENT_IDS["vitamin_a"]:
                summary.vitamin_a_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["vitamin_c"]:
                summary.vitamin_c_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["vitamin_d"]:
                summary.vitamin_d_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["vitamin_e"]:
                summary.vitamin_e_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["vitamin_k"]:
                summary.vitamin_k_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["vitamin_b12"]:
                summary.vitamin_b12_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["folate"]:
                summary.folate_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["calcium"]:
                summary.calcium_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["iron"]:
                summary.iron_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["magnesium"]:
                summary.magnesium_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["potassium"]:
                summary.potassium_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["zinc"]:
                summary.zinc_mg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["selenium"]:
                summary.selenium_mcg = m.amount
            elif m.nutrient_id == NUTRIENT_IDS["caffeine"]:
                summary.caffeine_mg = m.amount

        return summary

    # =========================================================================
    # Daily Statistics
    # =========================================================================

    async def get_daily_stats(
        self,
        user_id: str,
        target_date: date,
        include_supplements: bool = True,
        include_planned: bool = True,
    ) -> DailyNutritionStats:
        """Get comprehensive nutrition stats for a single day.

        If include_planned=True (default): includes ALL planned meals for the day.
        If include_planned=False: only includes CONSUMED meals:
        - Manually consumed (is_logged = true)
        - Auto-consumed (scheduled_time has passed, if auto_consume enabled)
        """
        client = get_supabase_client()
        from datetime import datetime

        date_str = target_date.isoformat()
        today = date.today()
        now = datetime.now()
        current_time_str = now.strftime("%H:%M:%S")

        # Load user preferences for auto_consume setting
        auto_consume_enabled = False
        try:
            prefs_result = (
                client.table(TABLES["prefs"])
                .select("auto_consume_meals, manual_consume_enabled")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if prefs_result.data:
                auto_consume_enabled = prefs_result.data.get("auto_consume_meals") or False
        except Exception as e:
            logger.debug(f"Could not load prefs for consumption check: {e}")

        # Load plan entries for the day
        entries_result = (
            client.table(TABLES["plan"])
            .select("*")
            .eq("user_id", user_id)
            .eq("planned_date", date_str)
            .execute()
        )
        all_entries = entries_result.data or []

        # Load consumption records to check what's been consumed
        consumed_entry_ids = set()
        try:
            consumption_result = (
                client.table(TABLES["consumption"])
                .select("plan_entry_id")
                .eq("user_id", user_id)
                .eq("meal_planned_date", date_str)
                .execute()
            )
            for c in consumption_result.data or []:
                if c.get("plan_entry_id"):
                    consumed_entry_ids.add(c["plan_entry_id"])
        except Exception as e:
            logger.debug(f"Could not load consumption records: {e}")

        # Filter entries based on include_planned flag
        if include_planned:
            # Include ALL planned entries for the day
            entries = all_entries
            logger.info(f"Daily nutrition: including all {len(entries)} planned entries for {date_str}")
        else:
            # Filter to only consumed entries
            entries = []
            for e in all_entries:
                is_consumed = False
                entry_id = e.get("id")

                # Check if consumed via consumption table (auto or manual)
                if entry_id in consumed_entry_ids:
                    is_consumed = True
                # Check is_logged flag (manual flag on entry)
                elif e.get("is_logged"):
                    is_consumed = True
                # Check auto-consumption by time (fallback if consumption record missing)
                elif auto_consume_enabled:
                    scheduled_time = e.get("scheduled_time")
                    if target_date < today:
                        # Past days - all meals are auto-consumed
                        is_consumed = True
                    elif target_date == today and scheduled_time:
                        # Today - check if scheduled time has passed
                        if scheduled_time <= current_time_str:
                            is_consumed = True

                if is_consumed:
                    entries.append(e)

            logger.info(f"Daily nutrition: {len(entries)}/{len(all_entries)} entries consumed for {date_str} (consumed_ids: {len(consumed_entry_ids)})")

        # Load supplements if requested
        supplements = []
        if include_supplements:
            try:
                supp_result = (
                    client.table(TABLES["supplements"])
                    .select("*")
                    .eq("user_id", user_id)
                    .execute()
                )
                supplements = supp_result.data or []
            except Exception as e:
                logger.warning(f"Failed to load supplements: {e}")

        # Collect all food item IDs
        food_item_ids = set()
        for e in entries:
            food_item_ids.add(e["food_item_id"])
        for s in supplements:
            food_item_ids.add(s.get("food_item_id"))

        if not food_item_ids:
            # No entries, return empty stats
            return DailyNutritionStats(
                date=target_date,
                nutrition=NutritionSummary(
                    macros=Macros(),
                    micronutrients=[],
                ),
            )

        # Load food items
        items_result = (
            client.table(TABLES["items"])
            .select("*")
            .in_("id", list(food_item_ids))
            .execute()
        )
        items_by_id = {i["id"]: i for i in (items_result.data or [])}

        # Calculate nutrition
        items_list = []
        amounts_list = []
        meals_logged = 0

        for e in entries:
            item = items_by_id.get(e["food_item_id"])
            if not item:
                continue

            scale = e.get("scale_factor") or 1

            # For ingredients/products, scale_factor is grams - use directly
            if item.get("kind") in ("ingredient", "product"):
                items_list.append(item)
                amounts_list.append(scale)
            else:
                # For meals/snacks, flatten the recipe to get actual ingredients
                # This ensures we capture micronutrients from the ingredients
                try:
                    logger.info(f"Flattening {item.get('kind')} '{item.get('name')}' ({item['id'][:8]}...) for nutrition")
                    flattened = await flatten_recipe_auto_owner(
                        recipe_id=item["id"],
                        user_id=user_id,
                        scale_factor=scale,
                        include_micronutrients=True,
                        include_rda=False,  # We'll calculate RDA later
                    )
                    logger.info(f"Flattened '{flattened.recipe_name}': {len(flattened.ingredients)} ingredients, {flattened.nutrition.total_calories} cal")
                    # Add each ingredient with its scaled amount
                    for ing in flattened.ingredients:
                        # Convert ingredient to dict format expected by nutrition calc
                        ing_dict = {
                            "id": ing.ingredient_id,
                            "name": ing.ingredient_name,
                            "kind": ing.ingredient_kind,
                            "calories_per_100g": ing.calories_per_100g,
                            "protein_g_per_100g": ing.protein_g_per_100g,
                            "carbs_g_per_100g": ing.carbs_g_per_100g,
                            "fat_g_per_100g": ing.fat_g_per_100g,
                            "micronutrients": ing.micronutrients or [],
                        }
                        items_list.append(ing_dict)
                        amounts_list.append(ing.amount_g)
                except Exception as flatten_err:
                    logger.warning(f"Failed to flatten recipe {item['id']}: {flatten_err}")
                    # Fallback: use the meal item directly (no micronutrients)
                    base_cal = item.get("base_calories") or item.get("calories_per_100g") or 100
                    cal_per_100g = item.get("calories_per_100g") or base_cal
                    if cal_per_100g > 0:
                        amount_g = (base_cal * scale * 100) / cal_per_100g
                    else:
                        amount_g = 100 * scale
                    items_list.append(item)
                    amounts_list.append(amount_g)

            if e.get("is_logged"):
                meals_logged += 1

        # Add supplements
        supplements_logged = 0
        for s in supplements:
            item = items_by_id.get(s.get("food_item_id"))
            if not item:
                continue

            amount_g = s.get("amount_g") or 100
            count = s.get("serving_count") or 1
            items_list.append(item)
            amounts_list.append(amount_g * count)
            supplements_logged += 1

        # Calculate nutrition summary
        nutrition = self.create_nutrition_summary(items_list, amounts_list, include_rda=True)

        # Load user prefs for target calories
        target_calories = None
        try:
            prefs_result = (
                client.table(TABLES["prefs"])
                .select("daily_calories")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if prefs_result.data:
                target_calories = prefs_result.data.get("daily_calories")
        except Exception:
            pass

        # Calculate scores
        vitamin_scores = []
        mineral_scores = []
        for m in nutrition.micronutrients:
            if m.percent_rda is not None:
                score = min(100, m.percent_rda)  # Cap at 100%
                if m.category == NutrientCategory.VITAMIN:
                    vitamin_scores.append(score)
                elif m.category == NutrientCategory.MINERAL:
                    mineral_scores.append(score)

        vitamin_score = sum(vitamin_scores) / len(vitamin_scores) if vitamin_scores else 0
        mineral_score = sum(mineral_scores) / len(mineral_scores) if mineral_scores else 0
        overall_score = (vitamin_score * 0.5 + mineral_score * 0.5)

        return DailyNutritionStats(
            date=target_date,
            nutrition=nutrition,
            target_calories=target_calories,
            calories_variance=(nutrition.macros.calories - target_calories) if target_calories else None,
            meals_logged=meals_logged,
            supplements_logged=supplements_logged,
            vitamin_score=vitamin_score,
            mineral_score=mineral_score,
            overall_nutrition_score=overall_score,
        )

    # =========================================================================
    # Analytics & Trends
    # =========================================================================

    async def get_nutrition_analytics(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> NutritionAnalytics:
        """Get comprehensive nutrition analytics over a date range."""
        # Calculate daily stats in parallel
        days = []
        current = start_date
        while current <= end_date:
            days.append(current)
            current += timedelta(days=1)

        # Fetch all daily stats concurrently
        tasks = [self.get_daily_stats(user_id, d) for d in days]
        daily_stats = await asyncio.gather(*tasks)

        # Aggregate totals
        total_items = []
        total_amounts = []
        calorie_values = []
        protein_values = []

        for stats in daily_stats:
            calorie_values.append((stats.date.isoformat(), stats.nutrition.macros.calories))
            protein_values.append((stats.date.isoformat(), stats.nutrition.macros.protein_g))

        # Calculate averages
        n_days = len(daily_stats) or 1

        avg_macros = Macros(
            calories=sum(s.nutrition.macros.calories for s in daily_stats) / n_days,
            protein_g=sum(s.nutrition.macros.protein_g for s in daily_stats) / n_days,
            carbs_g=sum(s.nutrition.macros.carbs_g for s in daily_stats) / n_days,
            fat_g=sum(s.nutrition.macros.fat_g for s in daily_stats) / n_days,
            fiber_g=sum(s.nutrition.macros.fiber_g for s in daily_stats) / n_days,
            sodium_mg=sum(s.nutrition.macros.sodium_mg for s in daily_stats) / n_days,
        )

        # Aggregate all micronutrients
        all_micros: dict[int, list[float]] = defaultdict(list)
        micro_info: dict[int, dict] = {}
        for stats in daily_stats:
            for m in stats.nutrition.micronutrients:
                all_micros[m.nutrient_id].append(m.amount)
                if m.nutrient_id not in micro_info:
                    micro_info[m.nutrient_id] = {
                        "name": m.name,
                        "unit": m.unit,
                        "category": m.category,
                    }

        avg_micros = []
        for nid, values in all_micros.items():
            info = micro_info[nid]
            avg_amount = sum(values) / len(values)

            micro = Micronutrient(
                nutrient_id=nid,
                name=info["name"],
                amount=avg_amount,
                unit=info["unit"],
                amount_mg=self._to_mg(avg_amount, info["unit"]),
                category=info["category"],
            )

            rda_info = get_rda_info(nid)
            if rda_info:
                avg_micros.append(MicronutrientWithRDA.from_micronutrient(
                    micro, rda=rda_info["rda"], rda_unit=rda_info["unit"]
                ))
            else:
                avg_micros.append(MicronutrientWithRDA(
                    nutrient_id=micro.nutrient_id,
                    name=micro.name,
                    amount=micro.amount,
                    unit=micro.unit,
                    amount_mg=micro.amount_mg,
                    category=micro.category,
                ))

        avg_micros.sort(key=lambda x: -(x.percent_rda or 0))

        average_daily = NutritionSummary(
            macros=avg_macros,
            micronutrients=avg_micros[:20],
            total_grams=sum(s.nutrition.total_grams for s in daily_stats) / n_days,
            item_count=int(sum(s.nutrition.item_count for s in daily_stats) / n_days),
        )

        # Calculate trends
        calorie_trend = self._calculate_trend("Calories", calorie_values)
        protein_trend = self._calculate_trend("Protein", protein_values)

        # Find deficient nutrients
        deficient = [m for m in avg_micros if m.status in ("deficient", "low")]

        # Calculate scores
        avg_nutrition_score = sum(s.overall_nutrition_score for s in daily_stats) / n_days

        # Consistency score: how consistent are daily calories?
        cal_values = [s.nutrition.macros.calories for s in daily_stats if s.nutrition.macros.calories > 0]
        if cal_values:
            mean_cal = sum(cal_values) / len(cal_values)
            variance = sum((c - mean_cal) ** 2 for c in cal_values) / len(cal_values)
            std_dev = variance ** 0.5
            cv = (std_dev / mean_cal) if mean_cal > 0 else 0
            consistency_score = max(0, 100 - (cv * 100))
        else:
            consistency_score = 0

        # Create total summary
        total_macros = Macros(
            calories=sum(s.nutrition.macros.calories for s in daily_stats),
            protein_g=sum(s.nutrition.macros.protein_g for s in daily_stats),
            carbs_g=sum(s.nutrition.macros.carbs_g for s in daily_stats),
            fat_g=sum(s.nutrition.macros.fat_g for s in daily_stats),
        )

        total_nutrition = NutritionSummary(
            macros=total_macros,
            micronutrients=[],  # Too many to include
            total_grams=sum(s.nutrition.total_grams for s in daily_stats),
        )

        return NutritionAnalytics(
            start_date=start_date,
            end_date=end_date,
            days_analyzed=n_days,
            daily_stats=daily_stats,
            average_daily=average_daily,
            total_nutrition=total_nutrition,
            calorie_trend=calorie_trend,
            protein_trend=protein_trend,
            top_nutrients=avg_micros[:10],
            deficient_nutrients=deficient[:5],
            average_nutrition_score=avg_nutrition_score,
            consistency_score=consistency_score,
        )

    def _calculate_trend(
        self,
        name: str,
        values: list[tuple[str, float]],
    ) -> NutritionTrend:
        """Calculate trend from date-value pairs."""
        if not values:
            return NutritionTrend(nutrient_name=name, values=[])

        numeric_values = [v for _, v in values]
        avg = sum(numeric_values) / len(numeric_values)
        min_val = min(numeric_values)
        max_val = max(numeric_values)

        # Compare first half to second half
        mid = len(numeric_values) // 2
        first_half = numeric_values[:mid] if mid > 0 else numeric_values
        second_half = numeric_values[mid:] if mid > 0 else numeric_values

        first_avg = sum(first_half) / len(first_half) if first_half else 0
        second_avg = sum(second_half) / len(second_half) if second_half else 0

        if first_avg > 0:
            pct_change = ((second_avg - first_avg) / first_avg) * 100
        else:
            pct_change = 0

        if abs(pct_change) < 10:
            direction = "stable"
        elif pct_change > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        return NutritionTrend(
            nutrient_name=name,
            values=values,
            average=avg,
            min_value=min_val,
            max_value=max_val,
            trend_direction=direction,
            percent_change=pct_change,
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _to_mg(self, amount: float, unit: str) -> Optional[float]:
        """Convert nutrient amount to milligrams."""
        unit = unit.lower().strip()
        if unit == "mg":
            return amount
        elif unit in ("µg", "ug", "mcg"):
            return amount / 1000
        elif unit == "g":
            return amount * 1000
        return None


# Singleton
_nutrition_service: Optional[NutritionService] = None


def get_nutrition_service() -> NutritionService:
    """Get singleton nutrition service."""
    global _nutrition_service
    if _nutrition_service is None:
        _nutrition_service = NutritionService()
    return _nutrition_service
