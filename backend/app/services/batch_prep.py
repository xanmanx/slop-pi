"""
Batch prep computation service.

Handles heavy compute for batch meal preparation:
- Recipe DAG flattening for multiple meals
- Ingredient aggregation across meals
- Grouping identical meals
- Organized display data structure
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Optional

from app.models.batch_prep import (
    BatchPrepIngredient,
    GroupedMeal,
    BatchPrepComputeResponse,
)
from app.services.recipes import flatten_recipe, get_recipe_graph_context
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


async def compute_batch_prep(
    user_id: str,
    plan_entry_ids: list[str],
    include_batch_instructions: bool = True,
) -> BatchPrepComputeResponse:
    """
    Compute batch prep data for a set of plan entries.

    This is the main heavy-compute endpoint that:
    1. Loads all plan entries
    2. Groups identical meals together
    3. Flattens all recipe DAGs in parallel
    4. Aggregates ingredients across all meals
    5. Returns organized display structure

    Args:
        user_id: The user ID
        plan_entry_ids: List of plan entry IDs to batch prep
        include_batch_instructions: Whether to include batch_prep_instructions

    Returns:
        BatchPrepComputeResponse with organized batch prep data
    """
    if not plan_entry_ids:
        return BatchPrepComputeResponse()

    logger.info(f"Computing batch prep for {len(plan_entry_ids)} plan entries")

    client = get_supabase_client()

    # Step 1: Load all plan entries
    entries_result = client.table(TABLES["plan"]).select("*").in_(
        "id", plan_entry_ids
    ).execute()

    entries = entries_result.data or []
    if not entries:
        logger.warning("No plan entries found")
        return BatchPrepComputeResponse()

    # Step 2: Get unique food item IDs
    food_item_ids = list(set(e["food_item_id"] for e in entries))

    # Step 3: Load food items
    items_result = client.table(TABLES["items"]).select("*").in_(
        "id", food_item_ids
    ).execute()
    items_by_id = {item["id"]: item for item in (items_result.data or [])}

    # Step 4: Load recipe nodes (for prep_steps and batch_prep_instructions)
    nodes_result = client.table(TABLES["recipe_nodes"]).select("*").in_(
        "food_item_id", food_item_ids
    ).execute()
    nodes_by_id = {node["food_item_id"]: node for node in (nodes_result.data or [])}

    # Step 5: Group entries by food_item_id
    entries_by_food_item: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        entries_by_food_item[entry["food_item_id"]].append(entry)

    # Step 6: Pre-load recipe graph context for efficiency
    # Collect owner IDs
    owner_ids = list(set(
        item.get("user_id") for item in items_by_id.values()
        if item.get("user_id")
    ))
    additional_owners = [oid for oid in owner_ids if oid != user_id]
    await get_recipe_graph_context(user_id, additional_owner_ids=additional_owners or None)

    # Step 7: Flatten all unique recipes in parallel
    flatten_tasks = []
    for food_item_id in food_item_ids:
        item = items_by_id.get(food_item_id)
        if not item:
            continue

        # Get scale factor from first entry (they should all be the same for identical meals)
        first_entry = entries_by_food_item[food_item_id][0]
        scale_factor = float(first_entry.get("scale_factor") or 1.0)

        owner_id = item.get("user_id")
        flatten_tasks.append(
            flatten_recipe(
                recipe_id=food_item_id,
                user_id=user_id,
                scale_factor=scale_factor,
                owner_id=owner_id,
            )
        )

    flattened_results = await asyncio.gather(*flatten_tasks, return_exceptions=True)

    # Build flattened map
    flattened_by_id: dict = {}
    for i, food_item_id in enumerate(food_item_ids):
        result = flattened_results[i]
        if isinstance(result, Exception):
            logger.error(f"Failed to flatten {food_item_id}: {result}")
            continue
        flattened_by_id[food_item_id] = result

    # Step 8: Build grouped meals
    grouped_meals: list[GroupedMeal] = []
    total_prep_time = 0
    total_cook_time = 0
    total_calories = 0.0
    total_protein = 0.0
    total_carbs = 0.0
    total_fat = 0.0

    # Aggregated ingredients across ALL meals
    all_ingredients: dict[str, BatchPrepIngredient] = {}

    for food_item_id, entry_list in entries_by_food_item.items():
        item = items_by_id.get(food_item_id)
        if not item:
            continue

        count = len(entry_list)
        flattened = flattened_by_id.get(food_item_id)
        recipe_node = nodes_by_id.get(food_item_id)

        # Build single-serving ingredients
        single_serving_ingredients: list[BatchPrepIngredient] = []
        batch_ingredients: list[BatchPrepIngredient] = []

        if flattened:
            for ing in flattened.ingredients:
                # Single serving
                single_ing = BatchPrepIngredient(
                    ingredient_id=ing.ingredient_id,
                    ingredient_name=ing.ingredient_name,
                    ingredient_kind=ing.ingredient_kind,
                    total_amount_g=ing.amount_g,
                    per_serving_g=ing.amount_g,
                    servings=1,
                    source_meal_ids=[food_item_id],
                    source_meal_names=[item.get("name", "Unknown")],
                    calories_per_100g=ing.calories_per_100g,
                    protein_g_per_100g=ing.protein_g_per_100g,
                    carbs_g_per_100g=ing.carbs_g_per_100g,
                    fat_g_per_100g=ing.fat_g_per_100g,
                )
                single_serving_ingredients.append(single_ing)

                # Batch (scaled by count)
                batch_ing = BatchPrepIngredient(
                    ingredient_id=ing.ingredient_id,
                    ingredient_name=ing.ingredient_name,
                    ingredient_kind=ing.ingredient_kind,
                    total_amount_g=ing.amount_g * count,
                    per_serving_g=ing.amount_g,
                    servings=count,
                    source_meal_ids=[food_item_id],
                    source_meal_names=[item.get("name", "Unknown")],
                    calories_per_100g=ing.calories_per_100g,
                    protein_g_per_100g=ing.protein_g_per_100g,
                    carbs_g_per_100g=ing.carbs_g_per_100g,
                    fat_g_per_100g=ing.fat_g_per_100g,
                )
                batch_ingredients.append(batch_ing)

                # Aggregate to all ingredients
                if ing.ingredient_id in all_ingredients:
                    existing = all_ingredients[ing.ingredient_id]
                    existing.total_amount_g += ing.amount_g * count
                    existing.servings += count
                    if food_item_id not in existing.source_meal_ids:
                        existing.source_meal_ids.append(food_item_id)
                        existing.source_meal_names.append(item.get("name", "Unknown"))
                else:
                    all_ingredients[ing.ingredient_id] = BatchPrepIngredient(
                        ingredient_id=ing.ingredient_id,
                        ingredient_name=ing.ingredient_name,
                        ingredient_kind=ing.ingredient_kind,
                        total_amount_g=ing.amount_g * count,
                        per_serving_g=ing.amount_g,
                        servings=count,
                        source_meal_ids=[food_item_id],
                        source_meal_names=[item.get("name", "Unknown")],
                        calories_per_100g=ing.calories_per_100g,
                        protein_g_per_100g=ing.protein_g_per_100g,
                        carbs_g_per_100g=ing.carbs_g_per_100g,
                        fat_g_per_100g=ing.fat_g_per_100g,
                    )

        # Get nutrition for one serving
        calories_per_serving = 0.0
        protein_per_serving = 0.0
        carbs_per_serving = 0.0
        fat_per_serving = 0.0

        if flattened and flattened.nutrition:
            calories_per_serving = flattened.nutrition.total_calories
            protein_per_serving = flattened.nutrition.total_protein_g
            carbs_per_serving = flattened.nutrition.total_carbs_g
            fat_per_serving = flattened.nutrition.total_fat_g

        # Add to totals
        total_calories += calories_per_serving * count
        total_protein += protein_per_serving * count
        total_carbs += carbs_per_serving * count
        total_fat += fat_per_serving * count

        # Get timing
        prep_time = recipe_node.get("prep_time_minutes") if recipe_node else None
        cook_time = recipe_node.get("cook_time_minutes") if recipe_node else None

        if prep_time:
            total_prep_time += prep_time
        if cook_time:
            total_cook_time += cook_time

        # Build grouped meal
        grouped_meal = GroupedMeal(
            food_item_id=food_item_id,
            food_item_name=item.get("name", "Unknown"),
            food_item_kind=item.get("kind", "meal"),
            count=count,
            plan_entry_ids=[e["id"] for e in entry_list],
            single_serving_steps=recipe_node.get("prep_steps", []) if recipe_node else [],
            batch_prep_instructions=(
                recipe_node.get("batch_prep_instructions")
                if recipe_node and include_batch_instructions
                else None
            ),
            prep_time_minutes=prep_time,
            cook_time_minutes=cook_time,
            single_serving_ingredients=single_serving_ingredients,
            batch_ingredients=batch_ingredients,
            calories_per_serving=calories_per_serving,
            protein_g_per_serving=protein_per_serving,
            carbs_g_per_serving=carbs_per_serving,
            fat_g_per_serving=fat_per_serving,
        )
        grouped_meals.append(grouped_meal)

    # Sort grouped meals by count (most frequent first)
    grouped_meals.sort(key=lambda m: -m.count)

    # Sort aggregated ingredients by total amount
    aggregated_ingredients = sorted(
        all_ingredients.values(),
        key=lambda i: -i.total_amount_g,
    )

    # Update per_serving_g for aggregated ingredients
    for ing in aggregated_ingredients:
        if ing.servings > 0:
            ing.per_serving_g = ing.total_amount_g / ing.servings

    total_meal_count = sum(m.count for m in grouped_meals)

    logger.info(
        f"Batch prep computed: {len(grouped_meals)} unique meals, "
        f"{total_meal_count} total servings, {len(aggregated_ingredients)} ingredients"
    )

    return BatchPrepComputeResponse(
        grouped_meals=grouped_meals,
        total_meal_count=total_meal_count,
        unique_meal_count=len(grouped_meals),
        aggregated_ingredients=aggregated_ingredients,
        total_prep_time_minutes=total_prep_time,
        total_cook_time_minutes=total_cook_time,
        total_calories=round(total_calories),
        total_protein_g=round(total_protein, 1),
        total_carbs_g=round(total_carbs, 1),
        total_fat_g=round(total_fat, 1),
    )
