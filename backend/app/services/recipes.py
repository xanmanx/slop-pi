"""
Recipe flattening and DAG traversal service.

Optimized for Raspberry Pi with:
- In-memory caching of recipe graphs (TTL: 5 minutes)
- Parallel batch flattening
- Pre-computed nutrition aggregations
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.models.nutrition import MicronutrientWithRDA, get_rda_info, categorize_nutrient, Micronutrient
from app.models.recipes import (
    FlattenedIngredient,
    RecipeNutrition,
    RecipeFlattened,
)
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


# ============================================================================
# Cache Configuration
# ============================================================================

# Recipe graph cache (cache_key -> context)
# Cache key includes user_id and any additional owner IDs
_graph_cache: dict[str, tuple[float, RecipeGraphContext]] = {}
_GRAPH_CACHE_TTL = 300  # 5 minutes

# Flattened recipe cache ((recipe_id, user_id, scale) -> result)
_flatten_cache: dict[tuple, tuple[float, RecipeFlattened]] = {}
_FLATTEN_CACHE_TTL = 600  # 10 minutes
_MAX_FLATTEN_CACHE_SIZE = 500


def clear_recipe_caches(user_id: Optional[str] = None):
    """Clear recipe caches, optionally for a specific user."""
    global _graph_cache, _flatten_cache

    if user_id:
        _graph_cache.pop(user_id, None)
        keys_to_remove = [k for k in _flatten_cache if k[1] == user_id]
        for k in keys_to_remove:
            _flatten_cache.pop(k, None)
    else:
        _graph_cache.clear()
        _flatten_cache.clear()


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class LegacyFlattenedIngredient:
    """Legacy format for backward compatibility."""
    ingredient_id: str
    ingredient_name: str
    ingredient_kind: str
    amount_g: float
    calories_per_100g: float = 0
    protein_g_per_100g: float = 0
    carbs_g_per_100g: float = 0
    fat_g_per_100g: float = 0
    micronutrients: list = field(default_factory=list)
    canonical_id: Optional[str] = None
    canonical_name: Optional[str] = None
    is_user_preference: bool = False


@dataclass
class RecipeGraphContext:
    """Cached recipe graph for efficient traversal."""
    item_map: dict  # id -> FoodItem
    edges_by_parent: dict  # parent_id -> list[RecipeEdge]
    node_map: dict  # food_item_id -> RecipeNode
    canonical_map: dict  # id -> CanonicalIngredient
    preference_map: dict  # canonical_id -> UserIngredientPreference
    loaded_at: float = 0


# ============================================================================
# Graph Context Loading
# ============================================================================

async def get_recipe_graph_context(
    user_id: str,
    force_refresh: bool = False,
    additional_owner_ids: Optional[list[str]] = None,
) -> RecipeGraphContext:
    """Load recipe graph context with caching.

    Loads all recipe data into memory for fast DAG traversal.
    Cached for 5 minutes per user.

    Args:
        user_id: The current user ID
        force_refresh: Force reload from database
        additional_owner_ids: Additional user IDs whose items should be included
            (e.g., recipe owner in household/team scenarios)
    """
    global _graph_cache

    now = time.time()

    # Build cache key that includes additional owners
    all_user_ids = sorted(set([user_id] + (additional_owner_ids or [])))
    cache_key = ":".join(all_user_ids)

    # Check cache
    if not force_refresh and cache_key in _graph_cache:
        cached_at, ctx = _graph_cache[cache_key]
        if now - cached_at < _GRAPH_CACHE_TTL:
            return ctx

    logger.info(f"Loading recipe graph for users {[u[:8] for u in all_user_ids]}...")
    start = time.time()

    client = get_supabase_client()

    # Build OR filter like the web app does - more reliable than separate queries
    # Format: "user_id.eq.xxx,user_id.is.null,is_public.eq.true"
    or_clauses = [f"user_id.eq.{uid}" for uid in all_user_ids]
    or_clauses.append("user_id.is.null")
    or_clauses.append("is_public.eq.true")
    or_filter = ",".join(or_clauses)

    logger.info(f"Using OR filter: {or_filter[:100]}...")

    # Load all data sequentially (more reliable than parallel with shared client)
    try:
        items_result = client.table(TABLES["items"]).select("*").or_(or_filter).execute()
        items_result_data = items_result.data or []
        logger.info(f"Items query returned {len(items_result_data)} items")
    except Exception as e:
        logger.error(f"Items query failed: {e}")
        items_result_data = []

    try:
        edges_result = client.table(TABLES["recipe_edges"]).select("*").or_(or_filter).execute()
        edges_result_data = edges_result.data or []
        logger.info(f"Edges query returned {len(edges_result_data)} edges")
        # Log breakdown
        user_owned = sum(1 for e in edges_result_data if e.get("user_id") in all_user_ids)
        public_edges = sum(1 for e in edges_result_data if e.get("is_public") is True)
        logger.info(f"Edge breakdown - user-owned: {user_owned}, public: {public_edges}, system: {len(edges_result_data) - user_owned - public_edges}")
    except Exception as e:
        logger.error(f"Edges query failed: {e}")
        edges_result_data = []

    try:
        nodes_result = client.table(TABLES["recipe_nodes"]).select("*").or_(or_filter).execute()
        nodes_result_data = nodes_result.data or []
        logger.info(f"Nodes query returned {len(nodes_result_data)} nodes")
    except Exception as e:
        logger.error(f"Nodes query failed: {e}")
        nodes_result_data = []

    try:
        canonicals_result = client.table("foodos2_canonical_ingredients").select("*").execute()
    except Exception as e:
        logger.error(f"Canonicals query failed: {e}")
        canonicals_result = None

    try:
        prefs_result = client.table("foodos2_user_ingredient_preferences").select("*").eq("user_id", user_id).execute()
    except Exception as e:
        logger.error(f"Prefs query failed: {e}")
        prefs_result = None

    logger.info(f"Graph data loaded: {len(items_result_data)} items, {len(edges_result_data)} edges, {len(nodes_result_data)} nodes")

    # Build maps from merged data
    item_map = {}
    for item in items_result_data:
        item_map[item["id"]] = item

    edges_by_parent = defaultdict(list)
    for edge in edges_result_data:
        edges_by_parent[edge["parent_food_item_id"]].append(edge)

    # Sort edges by sort_order
    for edges in edges_by_parent.values():
        edges.sort(key=lambda e: e.get("sort_order") or 0)

    node_map = {}
    for node in nodes_result_data:
        node_map[node["food_item_id"]] = node

    canonical_map = {}
    if canonicals_result and canonicals_result.data:
        for c in canonicals_result.data:
            canonical_map[c["id"]] = c

    preference_map = {}
    if prefs_result and prefs_result.data:
        for p in prefs_result.data:
            preference_map[p["canonical_id"]] = p

    ctx = RecipeGraphContext(
        item_map=item_map,
        edges_by_parent=dict(edges_by_parent),
        node_map=node_map,
        canonical_map=canonical_map,
        preference_map=preference_map,
        loaded_at=now,
    )

    # Cache it
    _graph_cache[cache_key] = (now, ctx)

    elapsed = (time.time() - start) * 1000
    logger.info(
        f"Recipe graph loaded: {len(item_map)} items, "
        f"{len(edges_by_parent)} recipe parents, {elapsed:.1f}ms"
    )

    return ctx


# ============================================================================
# Recipe Flattening
# ============================================================================

def _resolve_canonical(
    canonical_id: str,
    ctx: RecipeGraphContext,
) -> Optional[tuple[dict, bool]]:
    """Resolve canonical ingredient to FoodItem.

    Returns (item, is_user_preference) or None.
    """
    canonical = ctx.canonical_map.get(canonical_id)
    if not canonical:
        return None

    preference = ctx.preference_map.get(canonical_id)

    # If user has a preference with a specific product, use that
    if preference and preference.get("specific_food_item_id"):
        specific_item = ctx.item_map.get(preference["specific_food_item_id"])
        if specific_item:
            return (specific_item, True)

    # Otherwise, create a virtual FoodItem from canonical defaults
    virtual_item = {
        "id": f"canonical:{canonical_id}",
        "user_id": None,
        "kind": "ingredient",
        "name": canonical.get("name", "Unknown"),
        "calories_per_100g": canonical.get("calories_per_100g", 0),
        "protein_g_per_100g": canonical.get("protein_g_per_100g", 0),
        "carbs_g_per_100g": canonical.get("carbs_g_per_100g", 0),
        "fat_g_per_100g": canonical.get("fat_g_per_100g", 0),
        "micronutrients": canonical.get("micronutrients", []),
        "scaling_mode": "fixed",
        "is_premade": False,
        "notes": canonical.get("description"),
    }
    return (virtual_item, False)


async def flatten_recipe(
    recipe_id: str,
    user_id: str,
    scale_factor: float = 1.0,
    include_micronutrients: bool = True,
    include_rda: bool = True,
    use_cache: bool = True,
    owner_id: Optional[str] = None,
) -> RecipeFlattened:
    """Flatten a recipe DAG into ingredients with full nutrition.

    This is the main entry point for recipe flattening. Results are cached
    for 10 minutes to avoid redundant computation.

    Args:
        recipe_id: The food item ID of the recipe to flatten
        user_id: The current user ID (for preferences)
        scale_factor: Scale factor for ingredient amounts
        include_micronutrients: Include micronutrient data
        include_rda: Include RDA percentages
        use_cache: Use cached results if available
        owner_id: The owner of the recipe (if different from user_id,
            ensures owner's items are included in graph context)
    """
    global _flatten_cache

    now = time.time()
    cache_key = (recipe_id, user_id, scale_factor, owner_id)

    # Check cache
    if use_cache and cache_key in _flatten_cache:
        cached_at, result = _flatten_cache[cache_key]
        if now - cached_at < _FLATTEN_CACHE_TTL:
            return result

    # Load graph context (also cached)
    # Include owner_id to ensure recipe owner's items are accessible
    additional_owners = [owner_id] if owner_id and owner_id != user_id else None
    ctx = await get_recipe_graph_context(user_id, additional_owner_ids=additional_owners)

    # Get root item
    root_item = ctx.item_map.get(recipe_id)
    if not root_item:
        logger.warning(f"Recipe {recipe_id} not found in item_map (size: {len(ctx.item_map)})")
        # Debug: Check if item exists with user_id
        matching_items = [k for k, v in ctx.item_map.items() if v.get("name", "").lower().startswith("berry")]
        if matching_items:
            logger.warning(f"Found similar items: {matching_items[:3]}")
        return RecipeFlattened(
            recipe_id=recipe_id,
            recipe_name="Unknown",
            recipe_kind="meal",
            scale_factor=scale_factor,
            ingredients=[],
            nutrition=RecipeNutrition(),
            cycle_detected=False,
        )

    # Check if this recipe has edges
    edges_for_recipe = ctx.edges_by_parent.get(recipe_id, [])
    logger.info(f"Flattening recipe '{root_item.get('name')}' ({recipe_id[:8]}...) - found {len(edges_for_recipe)} edges")

    # Flatten the DAG
    ingredients_dict: dict[str, LegacyFlattenedIngredient] = {}
    cycle_detected = False
    max_depth = 0

    def walk(node_id: str, servings: float, path: set[str], depth: int):
        nonlocal cycle_detected, max_depth

        if node_id in path:
            cycle_detected = True
            return

        max_depth = max(max_depth, depth)
        next_path = path | {node_id}

        node = ctx.item_map.get(node_id)
        if not node:
            return

        children = ctx.edges_by_parent.get(node_id, [])
        if not children:
            return

        # Get base serving for proportional calculations
        recipe_node = ctx.node_map.get(node_id)
        base_serving_g = (recipe_node or {}).get("base_serving_g") or 0

        for edge in children:
            # Calculate amount based on storage mode
            storage_mode = edge.get("storage_mode")
            proportion = edge.get("proportion")

            if storage_mode == "proportional" and proportion is not None and base_serving_g > 0:
                amount = float(proportion) * base_serving_g
            else:
                amount = float(edge.get("amount_g") or 0)

            # Check for canonical ingredient reference
            canonical_id = edge.get("canonical_ingredient_id")
            if canonical_id:
                resolved = _resolve_canonical(canonical_id, ctx)
                if resolved:
                    item, is_user_pref = resolved
                    canonical = ctx.canonical_map.get(canonical_id, {})
                    item_id = item["id"]

                    if item_id in ingredients_dict:
                        ingredients_dict[item_id].amount_g += amount * servings
                    else:
                        ingredients_dict[item_id] = LegacyFlattenedIngredient(
                            ingredient_id=item_id,
                            ingredient_name=item.get("name", "Unknown"),
                            ingredient_kind=item.get("kind", "ingredient"),
                            amount_g=amount * servings,
                            calories_per_100g=item.get("calories_per_100g") or 0,
                            protein_g_per_100g=item.get("protein_g_per_100g") or 0,
                            carbs_g_per_100g=item.get("carbs_g_per_100g") or 0,
                            fat_g_per_100g=item.get("fat_g_per_100g") or 0,
                            micronutrients=item.get("micronutrients") or [],
                            canonical_id=canonical_id,
                            canonical_name=canonical.get("name"),
                            is_user_preference=is_user_pref,
                        )
                continue

            # Legacy: direct child_food_item_id reference
            child_id = edge.get("child_food_item_id")
            child = ctx.item_map.get(child_id) if child_id else None
            if not child:
                continue

            child_kind = child.get("kind", "ingredient")

            if child_kind == "ingredient" or child_kind == "product":
                if child_id in ingredients_dict:
                    ingredients_dict[child_id].amount_g += amount * servings
                else:
                    ingredients_dict[child_id] = LegacyFlattenedIngredient(
                        ingredient_id=child_id,
                        ingredient_name=child.get("name", "Unknown"),
                        ingredient_kind=child_kind,
                        amount_g=amount * servings,
                        calories_per_100g=child.get("calories_per_100g") or 0,
                        protein_g_per_100g=child.get("protein_g_per_100g") or 0,
                        carbs_g_per_100g=child.get("carbs_g_per_100g") or 0,
                        fat_g_per_100g=child.get("fat_g_per_100g") or 0,
                        micronutrients=child.get("micronutrients") or [],
                    )
            else:
                # Sub-meal: recurse
                child_servings = servings * amount
                if child_servings > 0:
                    walk(child_id, child_servings, next_path, depth + 1)

    walk(recipe_id, scale_factor, set(), 0)

    # Convert to model format
    ingredients = []
    for legacy in ingredients_dict.values():
        mult = legacy.amount_g / 100
        ing = FlattenedIngredient(
            ingredient_id=legacy.ingredient_id,
            ingredient_name=legacy.ingredient_name,
            ingredient_kind=legacy.ingredient_kind,
            amount_g=legacy.amount_g,
            calories_per_100g=legacy.calories_per_100g,
            protein_g_per_100g=legacy.protein_g_per_100g,
            carbs_g_per_100g=legacy.carbs_g_per_100g,
            fat_g_per_100g=legacy.fat_g_per_100g,
            calories=legacy.calories_per_100g * mult,
            protein_g=legacy.protein_g_per_100g * mult,
            carbs_g=legacy.carbs_g_per_100g * mult,
            fat_g=legacy.fat_g_per_100g * mult,
            micronutrients=legacy.micronutrients if include_micronutrients else [],
            canonical_id=legacy.canonical_id,
            canonical_name=legacy.canonical_name,
            is_user_preference=legacy.is_user_preference,
        )
        ingredients.append(ing)

    # Compute nutrition
    nutrition = _compute_nutrition(ingredients, include_rda)

    # Get recipe metadata
    recipe_node = ctx.node_map.get(recipe_id)

    result = RecipeFlattened(
        recipe_id=recipe_id,
        recipe_name=root_item.get("name", "Unknown"),
        recipe_kind=root_item.get("kind", "meal"),
        scale_factor=scale_factor,
        ingredients=ingredients,
        ingredient_count=len(ingredients),
        nutrition=nutrition,
        prep_time_minutes=recipe_node.get("prep_time_minutes") if recipe_node else None,
        cook_time_minutes=recipe_node.get("cook_time_minutes") if recipe_node else None,
        prep_steps=recipe_node.get("prep_steps") or [] if recipe_node else [],
        cycle_detected=cycle_detected,
        max_depth=max_depth,
    )

    # Cache result (with size limit)
    if len(_flatten_cache) >= _MAX_FLATTEN_CACHE_SIZE:
        # Remove oldest entries
        sorted_keys = sorted(_flatten_cache.keys(), key=lambda k: _flatten_cache[k][0])
        for k in sorted_keys[:100]:
            _flatten_cache.pop(k, None)

    _flatten_cache[cache_key] = (now, result)

    return result


def _compute_nutrition(
    ingredients: list[FlattenedIngredient],
    include_rda: bool = True,
) -> RecipeNutrition:
    """Compute comprehensive nutrition from ingredients."""
    if not ingredients:
        return RecipeNutrition()

    total_calories = 0.0
    total_protein = 0.0
    total_carbs = 0.0
    total_fat = 0.0
    total_grams = 0.0
    total_fiber = 0.0
    total_sugar = 0.0
    total_sodium = 0.0
    total_sat_fat = 0.0

    # Micronutrient aggregation
    micro_totals: dict[int, dict] = {}

    for ing in ingredients:
        total_grams += ing.amount_g
        total_calories += ing.calories
        total_protein += ing.protein_g
        total_carbs += ing.carbs_g
        total_fat += ing.fat_g

        # Process micronutrients
        for m in ing.micronutrients:
            nid = m.get("nutrient_id")
            if not nid:
                continue

            per100 = m.get("amount_per_100g") or m.get("amount_mg_per_100g") or 0
            amount = per100 * (ing.amount_g / 100)

            # Track special macros
            if nid == 1079:  # Fiber
                total_fiber += amount
            elif nid == 2000:  # Sugar
                total_sugar += amount
            elif nid == 1093:  # Sodium
                total_sodium += amount
            elif nid == 1258:  # Saturated fat
                total_sat_fat += amount
            else:
                # Regular micronutrient
                if nid not in micro_totals:
                    micro_totals[nid] = {
                        "nutrient_id": nid,
                        "name": m.get("name", ""),
                        "amount": 0,
                        "unit": m.get("unit", "mg"),
                    }
                micro_totals[nid]["amount"] += amount

    # Convert micronutrients to RDA format
    top_micros = []
    for nid, data in micro_totals.items():
        micro = Micronutrient(
            nutrient_id=nid,
            name=data["name"],
            amount=data["amount"],
            unit=data["unit"],
            amount_mg=_to_mg(data["amount"], data["unit"]),
            category=categorize_nutrient(data["name"], nid),
        )

        if include_rda:
            rda_info = get_rda_info(nid)
            if rda_info:
                top_micros.append(MicronutrientWithRDA.from_micronutrient(
                    micro, rda=rda_info["rda"], rda_unit=rda_info["unit"]
                ))
            else:
                top_micros.append(MicronutrientWithRDA(
                    nutrient_id=micro.nutrient_id,
                    name=micro.name,
                    amount=micro.amount,
                    unit=micro.unit,
                    amount_mg=micro.amount_mg,
                    category=micro.category,
                ))
        else:
            top_micros.append(MicronutrientWithRDA(
                nutrient_id=micro.nutrient_id,
                name=micro.name,
                amount=micro.amount,
                unit=micro.unit,
                amount_mg=micro.amount_mg,
                category=micro.category,
            ))

    # Sort by RDA percentage or amount
    top_micros.sort(key=lambda x: (-(x.percent_rda or 0), -(x.amount_mg or 0)))

    # Calculate ratios and scores
    protein_ratio = (total_protein * 4 / total_calories) if total_calories > 0 else 0

    # Nutrition density: vitamins/minerals per 100 calories
    micro_score = sum(m.percent_rda or 0 for m in top_micros[:10]) / 10 if top_micros else 0
    density_score = micro_score * (100 / max(total_calories, 100))

    return RecipeNutrition(
        total_calories=round(total_calories),
        total_protein_g=round(total_protein, 1),
        total_carbs_g=round(total_carbs, 1),
        total_fat_g=round(total_fat, 1),
        total_grams=round(total_grams),
        calories_per_100g=round(total_calories * 100 / total_grams) if total_grams > 0 else 0,
        protein_g_per_100g=round(total_protein * 100 / total_grams, 1) if total_grams > 0 else 0,
        carbs_g_per_100g=round(total_carbs * 100 / total_grams, 1) if total_grams > 0 else 0,
        fat_g_per_100g=round(total_fat * 100 / total_grams, 1) if total_grams > 0 else 0,
        fiber_g=round(total_fiber, 1),
        sugar_g=round(total_sugar, 1),
        sodium_mg=round(total_sodium),
        saturated_fat_g=round(total_sat_fat, 1),
        top_micronutrients=top_micros[:15],
        protein_ratio=round(protein_ratio, 2),
        nutrition_density_score=round(density_score, 1),
    )


def _to_mg(amount: float, unit: str) -> Optional[float]:
    """Convert to milligrams."""
    unit = unit.lower().strip()
    if unit == "mg":
        return amount
    elif unit in ("µg", "ug", "mcg"):
        return amount / 1000
    elif unit == "g":
        return amount * 1000
    return None


# ============================================================================
# Batch Operations
# ============================================================================

async def flatten_recipes_batch(
    recipe_ids: list[str],
    user_id: str,
    scale_factors: Optional[dict[str, float]] = None,
    owner_ids: Optional[dict[str, str]] = None,
) -> list[RecipeFlattened]:
    """Flatten multiple recipes in parallel.

    This is significantly faster than calling flatten_recipe() in a loop
    because the graph context is shared.

    Args:
        recipe_ids: List of recipe IDs to flatten
        user_id: Current user ID (for preferences)
        scale_factors: Optional dict of recipe_id -> scale factor
        owner_ids: Optional dict of recipe_id -> owner_id (for cross-user recipes)
    """
    if not recipe_ids:
        return []

    # Collect all unique owner IDs
    all_owner_ids = set()
    if owner_ids:
        all_owner_ids.update(owner_ids.values())

    # Pre-load graph context once with all owners
    additional_owners = list(all_owner_ids - {user_id}) if all_owner_ids else None
    await get_recipe_graph_context(user_id, additional_owner_ids=additional_owners)

    # Flatten all recipes concurrently
    tasks = []
    for rid in recipe_ids:
        scale = (scale_factors or {}).get(rid, 1.0)
        owner = (owner_ids or {}).get(rid)
        tasks.append(flatten_recipe(rid, user_id, scale, owner_id=owner))

    return await asyncio.gather(*tasks)


async def get_recipe_owner(recipe_id: str) -> Optional[str]:
    """Get the owner user_id of a recipe.

    Useful for looking up the owner before flattening a cross-user recipe.
    """
    client = get_supabase_client()
    result = client.table(TABLES["items"]).select("user_id").eq("id", recipe_id).single().execute()
    if result.data:
        return result.data.get("user_id")
    return None


async def flatten_recipe_auto_owner(
    recipe_id: str,
    user_id: str,
    scale_factor: float = 1.0,
    include_micronutrients: bool = True,
    include_rda: bool = True,
    use_cache: bool = True,
) -> RecipeFlattened:
    """Flatten a recipe, automatically detecting the owner.

    This is a convenience wrapper that looks up the recipe owner first,
    ensuring cross-user recipes (e.g., household/team) can be flattened.
    """
    # Look up the recipe owner
    owner_id = await get_recipe_owner(recipe_id)

    return await flatten_recipe(
        recipe_id=recipe_id,
        user_id=user_id,
        scale_factor=scale_factor,
        include_micronutrients=include_micronutrients,
        include_rda=include_rda,
        use_cache=use_cache,
        owner_id=owner_id,
    )


# ============================================================================
# Legacy Compatibility
# ============================================================================

async def flatten_recipe_dag(
    root_food_item_id: str,
    user_id: str,
    scale_factor: float = 1.0,
) -> tuple[dict[str, LegacyFlattenedIngredient], bool]:
    """Legacy API: Flatten recipe and return dict + cycle flag.

    For backward compatibility with existing code.
    """
    result = await flatten_recipe(root_food_item_id, user_id, scale_factor)

    # Convert back to legacy format
    ingredients_dict = {}
    for ing in result.ingredients:
        ingredients_dict[ing.ingredient_id] = LegacyFlattenedIngredient(
            ingredient_id=ing.ingredient_id,
            ingredient_name=ing.ingredient_name,
            ingredient_kind=ing.ingredient_kind,
            amount_g=ing.amount_g,
            calories_per_100g=ing.calories_per_100g,
            protein_g_per_100g=ing.protein_g_per_100g,
            carbs_g_per_100g=ing.carbs_g_per_100g,
            fat_g_per_100g=ing.fat_g_per_100g,
            micronutrients=ing.micronutrients,
            canonical_id=ing.canonical_id,
            canonical_name=ing.canonical_name,
            is_user_preference=ing.is_user_preference,
        )

    return ingredients_dict, result.cycle_detected


def compute_recipe_macros(
    ingredients_by_id: dict[str, LegacyFlattenedIngredient],
) -> dict:
    """Legacy API: Compute macros from flattened ingredients dict."""
    total_calories = 0.0
    total_protein_g = 0.0
    total_carbs_g = 0.0
    total_fat_g = 0.0
    total_grams = 0.0

    for flat_ing in ingredients_by_id.values():
        amount_g = flat_ing.amount_g
        total_grams += amount_g

        total_calories += (flat_ing.calories_per_100g * amount_g) / 100
        total_protein_g += (flat_ing.protein_g_per_100g * amount_g) / 100
        total_carbs_g += (flat_ing.carbs_g_per_100g * amount_g) / 100
        total_fat_g += (flat_ing.fat_g_per_100g * amount_g) / 100

    return {
        "total_calories": round(total_calories),
        "total_protein_g": round(total_protein_g * 10) / 10,
        "total_carbs_g": round(total_carbs_g * 10) / 10,
        "total_fat_g": round(total_fat_g * 10) / 10,
        "total_grams": round(total_grams),
        "calories_per_100g": round((total_calories * 100) / total_grams) if total_grams > 0 else 0,
        "protein_g_per_100g": round((total_protein_g * 100) / total_grams * 10) / 10 if total_grams > 0 else 0,
        "carbs_g_per_100g": round((total_carbs_g * 100) / total_grams * 10) / 10 if total_grams > 0 else 0,
        "fat_g_per_100g": round((total_fat_g * 100) / total_grams * 10) / 10 if total_grams > 0 else 0,
    }


async def get_ingredients_for_plan_entry(
    plan_entry_id: str,
    user_id: str,
) -> list[LegacyFlattenedIngredient]:
    """Get flattened ingredients for a plan entry."""
    client = get_supabase_client()

    # Load plan entry
    entry_result = client.table(TABLES["plan"]).select("*").eq(
        "id", plan_entry_id
    ).eq("user_id", user_id).single().execute()

    if not entry_result.data:
        raise ValueError(f"Plan entry not found: {plan_entry_id}")

    entry = entry_result.data
    food_item_id = entry["food_item_id"]
    scale_factor = float(entry.get("scale_factor") or 1)

    # Load food item
    item_result = client.table(TABLES["items"]).select("*").eq(
        "id", food_item_id
    ).single().execute()

    if not item_result.data:
        raise ValueError(f"Food item not found: {food_item_id}")

    item = item_result.data
    kind = item.get("kind", "ingredient")

    if kind in ("ingredient", "product"):
        # Direct ingredient/product: scale_factor is GRAMS
        grams = scale_factor if 0 < scale_factor <= 5000 else 100
        return [LegacyFlattenedIngredient(
            ingredient_id=item["id"],
            ingredient_name=item.get("name", "Unknown"),
            ingredient_kind=kind,
            amount_g=grams,
            calories_per_100g=item.get("calories_per_100g") or 0,
            protein_g_per_100g=item.get("protein_g_per_100g") or 0,
            carbs_g_per_100g=item.get("carbs_g_per_100g") or 0,
            fat_g_per_100g=item.get("fat_g_per_100g") or 0,
            micronutrients=item.get("micronutrients") or [],
        )]

    # Recipe: flatten to ingredients
    ingredients_dict, _ = await flatten_recipe_dag(food_item_id, user_id, scale_factor)
    return list(ingredients_dict.values())
