"""
Meal planning service with batch prep support.

Handles:
- Plan generation based on preferences
- Batch prep scheduling
- Meal scaling and nutrition calculation
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from app.models.nutrition import Macros
from app.models.planning import (
    DaySummary,
    HouseholdPlanRequest,
    HouseholdPlanResult,
    MealCandidate,
    PlanEntry,
    PlanGenerationRequest,
    PlanGenerationResult,
    PlanSlot,
    SlotTargets,
)
from app.services.recipes import flatten_recipe, get_recipe_graph_context
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


# ============================================================================
# Slot Calorie Distribution
# ============================================================================

DEFAULT_SLOT_DISTRIBUTION = {
    PlanSlot.BREAKFAST: 0.25,
    PlanSlot.LUNCH: 0.30,
    PlanSlot.DINNER: 0.30,
    PlanSlot.SNACK: 0.15,
}


def calculate_slot_targets(
    daily_calories: float,
    breakfasts: int = 1,
    lunches: int = 1,
    dinners: int = 1,
    snacks: int = 2,
) -> SlotTargets:
    """Calculate per-slot calorie targets."""
    # Distribute calories across slots
    breakfast_cals = daily_calories * DEFAULT_SLOT_DISTRIBUTION[PlanSlot.BREAKFAST] / max(breakfasts, 1)
    lunch_cals = daily_calories * DEFAULT_SLOT_DISTRIBUTION[PlanSlot.LUNCH] / max(lunches, 1)
    dinner_cals = daily_calories * DEFAULT_SLOT_DISTRIBUTION[PlanSlot.DINNER] / max(dinners, 1)
    snack_cals = daily_calories * DEFAULT_SLOT_DISTRIBUTION[PlanSlot.SNACK] / max(snacks, 1)

    return SlotTargets(
        breakfast=round(breakfast_cals),
        lunch=round(lunch_cals),
        dinner=round(dinner_cals),
        snack=round(snack_cals),
    )


# ============================================================================
# Meal Selection
# ============================================================================

async def get_meal_candidates(
    user_id: str,
    slot: PlanSlot,
    exclude_item_ids: Optional[set[str]] = None,
    pool_ids: Optional[list[str]] = None,
) -> list[MealCandidate]:
    """Get candidate meals for a slot.

    Filters by:
    - Meal pools (if specified)
    - Recent usage (variety)
    - Kind appropriate for slot
    """
    client = get_supabase_client()

    # Load user's food items
    items_result = client.table(TABLES["items"]).select("*").or_(
        f"user_id.eq.{user_id},user_id.is.null,is_public.eq.true"
    ).execute()

    items = items_result.data or []
    candidates: list[MealCandidate] = []

    for item in items:
        item_id = item["id"]

        # Skip excluded items
        if exclude_item_ids and item_id in exclude_item_ids:
            continue

        # Filter by kind
        kind = item.get("kind", "ingredient")
        if kind == "ingredient":
            continue

        # For now, allow all meals/snacks/products for any slot
        # In production, you'd filter based on pools and preferences

        base_calories = float(item.get("base_calories") or item.get("calories_per_100g") or 0)
        if base_calories <= 0:
            continue

        candidates.append(MealCandidate(
            food_item_id=item_id,
            name=item.get("name", "Unknown"),
            kind=kind,
            base_calories=base_calories,
            calories_per_100g=item.get("calories_per_100g"),
            protein_g_per_100g=item.get("protein_g_per_100g"),
            carbs_g_per_100g=item.get("carbs_g_per_100g"),
            fat_g_per_100g=item.get("fat_g_per_100g"),
            total_score=random.random(),  # Simple random selection for now
        ))

    # Sort by score
    candidates.sort(key=lambda x: -x.total_score)

    return candidates[:20]


def select_meal_for_slot(
    candidates: list[MealCandidate],
    target_calories: float,
) -> Optional[tuple[MealCandidate, float]]:
    """Select a meal and calculate scale factor to hit target calories."""
    if not candidates:
        return None

    # Pick a random meal from top candidates
    candidate = random.choice(candidates[:5]) if len(candidates) >= 5 else candidates[0]

    # Calculate scale factor
    if candidate.base_calories > 0:
        scale = target_calories / candidate.base_calories
        # Clamp to reasonable range
        scale = max(0.25, min(scale, 4.0))
    else:
        scale = 1.0

    return (candidate, scale)


# ============================================================================
# Plan Generation
# ============================================================================

async def generate_plan(request: PlanGenerationRequest) -> PlanGenerationResult:
    """Generate a meal plan for the given date range.

    Process:
    1. Load user preferences
    2. Calculate daily targets
    3. For each day and slot, select a meal
    4. Create plan entries
    """
    start_time = time.time()
    user_id = request.user_id
    start_date = request.start_date
    days = request.days

    logger.info(f"Generating plan for {user_id[:8]} from {start_date} for {days} days")

    client = get_supabase_client()

    # Load user preferences
    prefs_result = client.table(TABLES.get("prefs", "foodos2_preference_profiles")).select("*").eq(
        "user_id", user_id
    ).single().execute()

    prefs = prefs_result.data or {}

    # Calculate targets
    daily_calories = request.daily_calories or float(prefs.get("daily_calorie_target") or 2000)

    slot_targets = calculate_slot_targets(
        daily_calories,
        request.breakfasts_per_day,
        request.lunches_per_day,
        request.dinners_per_day,
        request.snacks_per_day,
    )

    # Get recent meals to avoid (for variety)
    recent_item_ids: set[str] = set()
    if request.avoid_recent_meals:
        lookback_start = start_date - timedelta(days=request.lookback_days)
        recent_result = client.table(TABLES["plan"]).select("food_item_id").eq(
            "user_id", user_id
        ).gte("planned_date", str(lookback_start)).execute()

        recent_item_ids = {e["food_item_id"] for e in (recent_result.data or [])}

    # Pre-load recipe context
    await get_recipe_graph_context(user_id)

    # Generate entries for each day
    entries: list[PlanEntry] = []
    daily_summaries: list[DaySummary] = []
    used_item_ids: set[str] = set()
    warnings: list[str] = []

    for day_offset in range(days):
        current_date = start_date + timedelta(days=day_offset)
        day_entries: list[PlanEntry] = []
        day_calories = 0.0
        day_protein = 0.0
        day_carbs = 0.0
        day_fat = 0.0
        meal_names: list[str] = []
        slots_filled: dict[str, int] = {}

        # Generate meals for each slot
        for slot, count in [
            (PlanSlot.BREAKFAST, request.breakfasts_per_day),
            (PlanSlot.LUNCH, request.lunches_per_day),
            (PlanSlot.DINNER, request.dinners_per_day),
            (PlanSlot.SNACK, request.snacks_per_day),
        ]:
            target = getattr(slot_targets, slot.value)

            for _ in range(count):
                # Get candidates excluding recently used
                exclude = recent_item_ids | used_item_ids
                candidates = await get_meal_candidates(
                    user_id, slot, exclude, request.allowed_pool_ids
                )

                if not candidates:
                    warnings.append(f"No candidates for {slot.value} on {current_date}")
                    continue

                # Select meal
                result = select_meal_for_slot(candidates, target)
                if not result:
                    continue

                meal, scale = result
                used_item_ids.add(meal.food_item_id)

                # Calculate nutrition
                est_cals = meal.base_calories * scale
                est_protein = (meal.protein_g_per_100g or 0) * scale
                est_carbs = (meal.carbs_g_per_100g or 0) * scale
                est_fat = (meal.fat_g_per_100g or 0) * scale

                entry = PlanEntry(
                    user_id=user_id,
                    food_item_id=meal.food_item_id,
                    food_item_name=meal.name,
                    food_item_kind=meal.kind,
                    planned_date=current_date,
                    slot=slot,
                    scale_factor=round(scale, 2),
                    estimated_calories=round(est_cals),
                    estimated_protein_g=round(est_protein, 1),
                    estimated_carbs_g=round(est_carbs, 1),
                    estimated_fat_g=round(est_fat, 1),
                    source="generated",
                )

                day_entries.append(entry)
                day_calories += est_cals
                day_protein += est_protein
                day_carbs += est_carbs
                day_fat += est_fat
                meal_names.append(meal.name)
                slots_filled[slot.value] = slots_filled.get(slot.value, 0) + 1

        entries.extend(day_entries)

        # Day summary
        variance = day_calories - daily_calories
        variance_pct = (variance / daily_calories * 100) if daily_calories > 0 else 0

        daily_summaries.append(DaySummary(
            date=current_date,
            slots_filled=slots_filled,
            target_calories=daily_calories,
            planned_calories=round(day_calories),
            variance_calories=round(variance),
            variance_pct=round(variance_pct, 1),
            macros=Macros(
                calories=round(day_calories),
                protein_g=round(day_protein, 1),
                carbs_g=round(day_carbs, 1),
                fat_g=round(day_fat, 1),
            ),
            meal_names=meal_names,
        ))

    # Calculate totals
    total_cals = sum(e.estimated_calories for e in entries)
    avg_daily = total_cals / days if days > 0 else 0
    accuracy = (1 - abs(avg_daily - daily_calories) / daily_calories) * 100 if daily_calories > 0 else 0

    generation_time = (time.time() - start_time) * 1000

    logger.info(
        f"Generated {len(entries)} entries in {generation_time:.1f}ms "
        f"(avg {avg_daily:.0f} cal/day, {accuracy:.1f}% accuracy)"
    )

    return PlanGenerationResult(
        success=True,
        entries=entries,
        entries_created=len(entries),
        daily_summaries=daily_summaries,
        total_calories=round(total_cals),
        avg_daily_calories=round(avg_daily),
        target_daily_calories=daily_calories,
        calorie_accuracy_pct=round(accuracy, 1),
        warnings=warnings,
        generation_time_ms=round(generation_time, 1),
    )


async def save_plan_entries(entries: list[PlanEntry], user_id: str) -> int:
    """Save generated plan entries to database."""
    if not entries:
        return 0

    client = get_supabase_client()

    # Convert to database format
    rows = []
    for entry in entries:
        rows.append({
            "user_id": user_id,
            "food_item_id": entry.food_item_id,
            "planned_date": str(entry.planned_date),
            "slot": entry.slot.value,
            "scale_factor": entry.scale_factor,
            "scheduled_time": entry.time.isoformat() if entry.time else None,
            "is_logged": False,
            "notes": entry.notes,
        })

    result = client.table(TABLES["plan"]).insert(rows).execute()

    return len(result.data or [])


# ============================================================================
# Batch Prep
# ============================================================================

async def set_batch_prep(
    entry_ids: list[str],
    user_id: str,
    batch_prep_date: date,
    batch_prep_time: Optional[str] = None,
) -> int:
    """Mark entries for batch prep on a specific date."""
    if not entry_ids:
        return 0

    client = get_supabase_client()

    update_data = {
        "is_batch_prepped": True,
        "batch_prep_date": str(batch_prep_date),
    }
    if batch_prep_time:
        update_data["batch_prep_time"] = batch_prep_time

    # Update each entry
    updated = 0
    for entry_id in entry_ids:
        result = client.table(TABLES["plan"]).update(update_data).eq(
            "id", entry_id
        ).eq("user_id", user_id).execute()

        if result.data:
            updated += 1

    logger.info(f"Marked {updated} entries for batch prep on {batch_prep_date}")

    return updated


async def clear_batch_prep(entry_ids: list[str], user_id: str) -> int:
    """Clear batch prep settings from entries."""
    if not entry_ids:
        return 0

    client = get_supabase_client()

    update_data = {
        "is_batch_prepped": False,
        "batch_prep_date": None,
        "batch_prep_time": None,
    }

    updated = 0
    for entry_id in entry_ids:
        result = client.table(TABLES["plan"]).update(update_data).eq(
            "id", entry_id
        ).eq("user_id", user_id).execute()

        if result.data:
            updated += 1

    return updated


async def get_batch_prep_entries(
    user_id: str,
    batch_prep_date: date,
) -> list[dict]:
    """Get all entries scheduled for batch prep on a date."""
    client = get_supabase_client()

    result = client.table(TABLES["plan"]).select("*").eq(
        "user_id", user_id
    ).eq("batch_prep_date", str(batch_prep_date)).execute()

    return result.data or []


async def get_batch_prep_summary(
    user_id: str,
    batch_prep_date: date,
) -> dict:
    """Get summary of batch prep session.

    Returns aggregated ingredients and nutrition for all meals
    being prepped together.
    """
    entries = await get_batch_prep_entries(user_id, batch_prep_date)

    if not entries:
        return {
            "date": str(batch_prep_date),
            "entries_count": 0,
            "meals": [],
            "total_ingredients": [],
            "total_nutrition": {},
        }

    client = get_supabase_client()

    # Load food items
    item_ids = list({e["food_item_id"] for e in entries})
    items_result = client.table(TABLES["items"]).select("*").in_("id", item_ids).execute()
    item_map = {item["id"]: item for item in (items_result.data or [])}

    # Pre-load recipe context
    await get_recipe_graph_context(user_id)

    meals = []
    all_ingredients: dict[str, dict] = {}
    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fat = 0

    for entry in entries:
        food_item_id = entry["food_item_id"]
        item = item_map.get(food_item_id)
        if not item:
            continue

        scale = float(entry.get("scale_factor") or 1)

        meal_info = {
            "entry_id": entry["id"],
            "food_item_id": food_item_id,
            "name": item.get("name", "Unknown"),
            "kind": item.get("kind", "meal"),
            "scale_factor": scale,
            "planned_date": entry.get("planned_date"),
            "slot": entry.get("slot"),
        }

        kind = item.get("kind", "ingredient")

        if kind in ("ingredient", "product"):
            # Direct item
            grams = scale if 0 < scale <= 5000 else 100
            mult = grams / 100

            meal_info["calories"] = round((item.get("calories_per_100g") or 0) * mult)
            meal_info["protein_g"] = round((item.get("protein_g_per_100g") or 0) * mult, 1)
            meal_info["carbs_g"] = round((item.get("carbs_g_per_100g") or 0) * mult, 1)
            meal_info["fat_g"] = round((item.get("fat_g_per_100g") or 0) * mult, 1)

            # Add to aggregated ingredients
            ing_key = item["id"]
            if ing_key not in all_ingredients:
                all_ingredients[ing_key] = {
                    "id": item["id"],
                    "name": item.get("name", "Unknown"),
                    "amount_g": 0,
                }
            all_ingredients[ing_key]["amount_g"] += grams

        else:
            # Recipe - flatten
            try:
                flattened = await flatten_recipe(
                    food_item_id, user_id, scale,
                    include_micronutrients=False, include_rda=False
                )

                meal_info["calories"] = flattened.nutrition.total_calories
                meal_info["protein_g"] = flattened.nutrition.total_protein_g
                meal_info["carbs_g"] = flattened.nutrition.total_carbs_g
                meal_info["fat_g"] = flattened.nutrition.total_fat_g
                meal_info["ingredients_count"] = len(flattened.ingredients)

                # Add ingredients to aggregation
                for ing in flattened.ingredients:
                    ing_key = ing.ingredient_id
                    if ing_key not in all_ingredients:
                        all_ingredients[ing_key] = {
                            "id": ing.ingredient_id,
                            "name": ing.ingredient_name,
                            "amount_g": 0,
                        }
                    all_ingredients[ing_key]["amount_g"] += ing.amount_g

            except Exception as e:
                logger.warning(f"Failed to flatten recipe {food_item_id}: {e}")
                meal_info["error"] = str(e)

        meals.append(meal_info)
        total_calories += meal_info.get("calories", 0)
        total_protein += meal_info.get("protein_g", 0)
        total_carbs += meal_info.get("carbs_g", 0)
        total_fat += meal_info.get("fat_g", 0)

    # Format ingredients list
    ingredients_list = sorted(
        [{"name": v["name"], "amount_g": round(v["amount_g"], 1)} for v in all_ingredients.values()],
        key=lambda x: -x["amount_g"]
    )

    return {
        "date": str(batch_prep_date),
        "entries_count": len(entries),
        "meals": meals,
        "total_ingredients": ingredients_list,
        "total_nutrition": {
            "calories": round(total_calories),
            "protein_g": round(total_protein, 1),
            "carbs_g": round(total_carbs, 1),
            "fat_g": round(total_fat, 1),
        },
    }


# ============================================================================
# Household Planning
# ============================================================================

async def generate_household_plan(request: HouseholdPlanRequest) -> HouseholdPlanResult:
    """Generate synchronized plans for household members.

    Shared meals (e.g., dinner) are planned once and assigned to all members
    with appropriate portion scaling based on individual calorie targets.
    """
    controller_id = request.controller_user_id
    controlled_ids = request.controlled_user_ids
    all_user_ids = [controller_id] + controlled_ids

    logger.info(f"Generating household plan for {len(all_user_ids)} users")

    client = get_supabase_client()

    # Load preferences for all users
    user_prefs = {}
    for uid in all_user_ids:
        prefs_result = client.table(TABLES.get("prefs", "foodos2_preference_profiles")).select("*").eq(
            "user_id", uid
        ).single().execute()

        prefs = prefs_result.data or {}
        user_prefs[uid] = {
            "daily_calories": request.user_calories.get(uid) if request.user_calories else None
                or float(prefs.get("daily_calorie_target") or 2000),
        }

    # Generate plans
    plans_by_user: dict[str, PlanGenerationResult] = {}
    shared_meals: set[str] = set()

    # Generate controller's plan first
    controller_plan = await generate_plan(PlanGenerationRequest(
        user_id=controller_id,
        start_date=request.start_date,
        days=request.days,
        daily_calories=user_prefs[controller_id]["daily_calories"],
    ))
    plans_by_user[controller_id] = controller_plan

    # Track shared meals from shared slots
    for entry in controller_plan.entries:
        if entry.slot in request.shared_slots:
            shared_meals.add(f"{entry.planned_date}:{entry.slot.value}")

    # Generate plans for controlled users
    # Reuse shared meals with scaled portions
    for uid in controlled_ids:
        user_plan = await generate_plan(PlanGenerationRequest(
            user_id=uid,
            start_date=request.start_date,
            days=request.days,
            daily_calories=user_prefs[uid]["daily_calories"],
        ))
        plans_by_user[uid] = user_plan

    # Collect unique ingredients
    all_ingredients: set[str] = set()
    for plan in plans_by_user.values():
        for entry in plan.entries:
            all_ingredients.add(entry.food_item_id)

    return HouseholdPlanResult(
        success=True,
        plans_by_user=plans_by_user,
        shared_meal_names=list(shared_meals),
        unique_ingredients_count=len(all_ingredients),
    )
