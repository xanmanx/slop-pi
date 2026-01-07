"""
Grocery list generation service.

Generates shopping lists from meal plans, reorders, and supplements.
Aggregates across household members and subtracts inventory.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from app.models.grocery import (
    GroceryCategory,
    GroceryItem,
    GroceryList,
    GroceryGenerationRequest,
)
from app.services.recipes import flatten_recipe, get_recipe_graph_context
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


# ============================================================================
# Category Detection
# ============================================================================

# Keywords for auto-categorization
CATEGORY_KEYWORDS: dict[GroceryCategory, list[str]] = {
    GroceryCategory.PRODUCE: [
        "apple", "banana", "orange", "lemon", "lime", "tomato", "onion", "garlic",
        "lettuce", "spinach", "kale", "carrot", "celery", "pepper", "cucumber",
        "broccoli", "cauliflower", "potato", "sweet potato", "mushroom", "avocado",
        "berry", "grape", "melon", "mango", "pineapple", "strawberry", "blueberry",
        "zucchini", "squash", "eggplant", "cabbage", "asparagus", "green bean",
    ],
    GroceryCategory.MEAT_SEAFOOD: [
        "chicken", "beef", "pork", "turkey", "lamb", "steak", "ground", "sausage",
        "bacon", "ham", "salmon", "tuna", "shrimp", "fish", "cod", "tilapia",
        "crab", "lobster", "scallop", "mussels", "oyster",
    ],
    GroceryCategory.DAIRY: [
        "milk", "cheese", "yogurt", "butter", "cream", "egg", "cottage cheese",
        "sour cream", "whipping cream", "half and half", "cream cheese",
    ],
    GroceryCategory.BAKERY: [
        "bread", "bagel", "muffin", "croissant", "roll", "bun", "tortilla",
        "pita", "naan", "english muffin",
    ],
    GroceryCategory.FROZEN: [
        "frozen", "ice cream", "popsicle", "frozen pizza", "frozen meal",
    ],
    GroceryCategory.PANTRY: [
        "rice", "pasta", "flour", "sugar", "oil", "vinegar", "sauce", "can",
        "bean", "lentil", "oat", "cereal", "nut", "seed", "honey", "syrup",
        "salt", "pepper", "spice", "seasoning", "broth", "stock",
    ],
    GroceryCategory.BEVERAGES: [
        "water", "juice", "soda", "coffee", "tea", "wine", "beer", "milk",
        "energy drink", "sports drink", "sparkling",
    ],
    GroceryCategory.SNACKS: [
        "chip", "cracker", "cookie", "candy", "chocolate", "granola bar",
        "protein bar", "popcorn", "pretzel", "nut",
    ],
    GroceryCategory.CONDIMENTS: [
        "ketchup", "mustard", "mayo", "mayonnaise", "relish", "hot sauce",
        "soy sauce", "teriyaki", "bbq sauce", "salsa", "dressing",
    ],
    GroceryCategory.SUPPLEMENTS: [
        "vitamin", "supplement", "protein powder", "creatine", "fish oil",
        "probiotic", "multivitamin", "mineral", "omega",
    ],
}


def detect_category(name: str) -> GroceryCategory:
    """Detect category from ingredient name."""
    name_lower = name.lower()

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name_lower:
                return category

    return GroceryCategory.OTHER


# ============================================================================
# Main Generation
# ============================================================================

async def generate_grocery_list(request: GroceryGenerationRequest) -> GroceryList:
    """Generate a grocery list for the given date range.

    Process:
    1. Load plan entries for date range
    2. Flatten all recipes to get ingredient requirements
    3. Add reorders if enabled
    4. Add supplements if enabled
    5. Aggregate by canonical ID or name
    6. Subtract inventory if enabled
    7. Categorize and sort
    """
    start = request.start_date
    end = request.end_date
    user_id = request.user_id

    logger.info(f"Generating grocery list for {user_id[:8]} from {start} to {end}")

    client = get_supabase_client()

    # Collect all user IDs to process
    user_ids = [user_id]
    if request.include_household and request.household_user_ids:
        user_ids.extend(request.household_user_ids)
    user_ids = list(set(user_ids))

    # -------------------------------------------------------------------------
    # Load plan entries
    # -------------------------------------------------------------------------

    all_entries = []
    if request.include_meals:
        for uid in user_ids:
            result = client.table(TABLES["plan"]).select("*").eq(
                "user_id", uid
            ).gte(
                "planned_date", str(start)
            ).lte(
                "planned_date", str(end)
            ).execute()

            if result.data:
                all_entries.extend(result.data)

    logger.info(f"Loaded {len(all_entries)} plan entries")

    # -------------------------------------------------------------------------
    # Load food items
    # -------------------------------------------------------------------------

    # Build access filter for all users
    access_filters = [f"user_id.eq.{uid}" for uid in user_ids]
    access_filters.append("user_id.is.null")
    access_filters.append("is_public.eq.true")
    access_filter = ",".join(access_filters)

    items_result = client.table(TABLES["items"]).select("*").or_(access_filter).execute()
    item_map = {item["id"]: item for item in (items_result.data or [])}

    # -------------------------------------------------------------------------
    # Load inventory
    # -------------------------------------------------------------------------

    inventory_map: dict[str, float] = {}
    if request.subtract_inventory:
        for uid in user_ids:
            inv_result = client.table(TABLES["inventory"]).select("*").eq(
                "user_id", uid
            ).execute()

            for inv in (inv_result.data or []):
                fid = inv["food_item_id"]
                qty = float(inv.get("quantity_g") or 0)
                inventory_map[fid] = inventory_map.get(fid, 0) + qty

    # -------------------------------------------------------------------------
    # Process plan entries -> aggregate needs
    # -------------------------------------------------------------------------

    # Aggregation key -> {needed_g, sources, item}
    needs: dict[str, dict] = {}

    # Pre-load recipe context for first user (shared)
    if all_entries:
        await get_recipe_graph_context(user_id)

    for entry in all_entries:
        food_item_id = entry["food_item_id"]
        item = item_map.get(food_item_id)
        if not item:
            continue

        scale = float(entry.get("scale_factor") or 1)
        kind = item.get("kind", "ingredient")
        entry_user = entry.get("user_id", user_id)

        if kind in ("ingredient", "product"):
            # Direct item
            grams = scale if 0 < scale <= 5000 else 100
            agg_key = _get_aggregation_key(item)

            if agg_key not in needs:
                needs[agg_key] = {
                    "item": item,
                    "needed_g": 0,
                    "from_meals": 0,
                    "from_reorders": 0,
                    "from_supplements": 0,
                    "meal_sources": set(),
                }

            needs[agg_key]["needed_g"] += grams
            needs[agg_key]["from_meals"] += grams
            needs[agg_key]["meal_sources"].add(item.get("name", "Unknown"))
        else:
            # Recipe - flatten it
            try:
                flattened = await flatten_recipe(
                    food_item_id, entry_user, scale,
                    include_micronutrients=False, include_rda=False
                )

                meal_name = item.get("name", "Unknown")

                for ing in flattened.ingredients:
                    # Get actual item for aggregation key
                    ing_item = item_map.get(ing.ingredient_id)
                    if not ing_item:
                        # Create virtual item from flattened data
                        ing_item = {
                            "id": ing.ingredient_id,
                            "name": ing.ingredient_name,
                            "kind": ing.ingredient_kind,
                        }

                    agg_key = _get_aggregation_key(ing_item, ing.canonical_id)

                    if agg_key not in needs:
                        needs[agg_key] = {
                            "item": ing_item,
                            "canonical_id": ing.canonical_id,
                            "needed_g": 0,
                            "from_meals": 0,
                            "from_reorders": 0,
                            "from_supplements": 0,
                            "meal_sources": set(),
                        }

                    needs[agg_key]["needed_g"] += ing.amount_g
                    needs[agg_key]["from_meals"] += ing.amount_g
                    needs[agg_key]["meal_sources"].add(meal_name)

            except Exception as e:
                logger.warning(f"Failed to flatten recipe {food_item_id}: {e}")

    # -------------------------------------------------------------------------
    # Add reorders
    # -------------------------------------------------------------------------

    reorders_count = 0
    if request.include_reorders:
        try:
            for uid in user_ids:
                reorder_result = client.table(TABLES.get("reorders", "foodos2_reorders")).select(
                    "*"
                ).eq("user_id", uid).execute()

                for reorder in (reorder_result.data or []):
                    fid = reorder["food_item_id"]
                    item = item_map.get(fid)
                    if not item:
                        continue

                    # Only include products (not ingredients)
                    if item.get("kind") == "ingredient":
                        continue

                    # Check if inventory is below reorder level
                    reorder_level = float(reorder.get("reorder_level_g") or 0)
                    current_inv = inventory_map.get(fid, 0)

                    if reorder_level > 0 and current_inv >= reorder_level:
                        continue

                    reorder_qty = float(reorder.get("reorder_quantity_g") or 0)
                    if reorder_qty <= 0:
                        continue

                    agg_key = _get_aggregation_key(item)

                    if agg_key not in needs:
                        needs[agg_key] = {
                            "item": item,
                            "needed_g": 0,
                            "from_meals": 0,
                            "from_reorders": 0,
                            "from_supplements": 0,
                            "meal_sources": set(),
                        }

                    needs[agg_key]["needed_g"] += reorder_qty
                    needs[agg_key]["from_reorders"] += reorder_qty
                    reorders_count += 1

        except Exception as e:
            logger.warning(f"Failed to load reorders: {e}")

    # -------------------------------------------------------------------------
    # Add supplements
    # -------------------------------------------------------------------------

    supplements_count = 0
    if request.include_supplements:
        try:
            days_in_range = (end - start).days + 1

            for uid in user_ids:
                supp_result = client.table(TABLES.get("supplements", "foodos2_supplements")).select(
                    "*"
                ).eq("user_id", uid).execute()

                for supp in (supp_result.data or []):
                    fid = supp["food_item_id"]
                    item = item_map.get(fid)
                    if not item:
                        continue

                    # Calculate occurrences in date range
                    schedule_type = supp.get("schedule_type", "daily")
                    occurrences = 0

                    if schedule_type == "daily":
                        occurrences = days_in_range
                    elif schedule_type == "every_other_day":
                        occurrences = (days_in_range + 1) // 2
                    elif schedule_type == "weekly":
                        days = supp.get("schedule_config", {}).get("days", [])
                        if days:
                            # Count matching days of week
                            current = start
                            while current <= end:
                                if current.weekday() in days:
                                    occurrences += 1
                                current += timedelta(days=1)
                        else:
                            occurrences = days_in_range // 7

                    if occurrences <= 0:
                        continue

                    amount_per_day = float(supp.get("amount_g") or 100) * float(supp.get("serving_count") or 1)
                    total_needed = amount_per_day * occurrences

                    agg_key = _get_aggregation_key(item)

                    if agg_key not in needs:
                        needs[agg_key] = {
                            "item": item,
                            "needed_g": 0,
                            "from_meals": 0,
                            "from_reorders": 0,
                            "from_supplements": 0,
                            "meal_sources": set(),
                        }

                    needs[agg_key]["needed_g"] += total_needed
                    needs[agg_key]["from_supplements"] += total_needed
                    supplements_count += 1

        except Exception as e:
            logger.warning(f"Failed to load supplements: {e}")

    # -------------------------------------------------------------------------
    # Build grocery items
    # -------------------------------------------------------------------------

    grocery_items: list[GroceryItem] = []

    for agg_key, data in needs.items():
        item = data["item"]
        needed = data["needed_g"]

        # Skip if below minimum
        if needed < request.minimum_amount_g:
            continue

        # Get inventory
        in_stock = inventory_map.get(item["id"], 0)
        to_buy = max(0, needed - in_stock) if request.subtract_inventory else needed

        # Detect category
        category = detect_category(item.get("name", ""))

        grocery_items.append(GroceryItem(
            ingredient_id=item.get("id"),
            canonical_id=data.get("canonical_id"),
            name=item.get("name", "Unknown"),
            needed_g=round(needed, 1),
            in_stock_g=round(in_stock, 1),
            to_buy_g=round(to_buy, 1),
            display_amount=_format_amount(to_buy),
            display_unit="g",
            category=category,
            from_meals=round(data.get("from_meals", 0), 1),
            from_reorders=round(data.get("from_reorders", 0), 1),
            from_supplements=round(data.get("from_supplements", 0), 1),
            meal_sources=list(data.get("meal_sources", set())),
        ))

    # Sort by category then name
    grocery_items.sort(key=lambda x: (x.category.value, x.name.lower()))

    # Group by category
    by_category: dict[str, list[GroceryItem]] = defaultdict(list)
    for item in grocery_items:
        by_category[item.category.value].append(item)

    # Build result
    items_to_buy = [i for i in grocery_items if i.to_buy_g > 0]

    result = GroceryList(
        start_date=start,
        end_date=end,
        days=(end - start).days + 1,
        items=grocery_items,
        items_count=len(grocery_items),
        items_to_buy_count=len(items_to_buy),
        by_category=dict(by_category),
        total_items_needed=len(grocery_items),
        items_in_stock=len([i for i in grocery_items if i.to_buy_g <= 0]),
        items_to_purchase=len(items_to_buy),
        user_ids=user_ids,
        is_household_list=len(user_ids) > 1,
        meals_included=len(all_entries),
        reorders_included=reorders_count,
        supplements_included=supplements_count,
    )

    logger.info(
        f"Generated grocery list: {len(grocery_items)} items, "
        f"{len(items_to_buy)} to buy"
    )

    return result


def _get_aggregation_key(item: dict, canonical_id: Optional[str] = None) -> str:
    """Get aggregation key for an item."""
    if canonical_id:
        return f"canonical:{canonical_id}"
    # Fall back to normalized name
    return f"name:{item.get('name', '').lower().strip()}"


def _format_amount(grams: float) -> str:
    """Format grams for display."""
    if grams >= 1000:
        return f"{round(grams / 1000, 1)}kg"
    elif grams >= 1:
        return f"{round(grams)}g"
    else:
        return f"{round(grams, 1)}g"
