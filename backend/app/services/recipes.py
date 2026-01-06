"""Recipe flattening and DAG traversal service.

Ported from xProj/lib/foodos2/recipes.ts
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


@dataclass
class FlattenedIngredient:
    """Result of flattening a recipe ingredient."""
    ingredient_id: str
    ingredient_name: str
    ingredient_kind: str
    amount_g: float
    calories_per_100g: float = 0
    protein_g_per_100g: float = 0
    carbs_g_per_100g: float = 0
    fat_g_per_100g: float = 0
    micronutrients: list = field(default_factory=list)
    # Canonical ingredient info
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


async def get_recipe_graph_context(user_id: str) -> RecipeGraphContext:
    """Load all recipe data for a user into memory for fast DAG traversal."""
    client = get_supabase_client()

    # Load all food items (user's + public/system)
    items_result = client.table(TABLES["items"]).select("*").or_(
        f"user_id.eq.{user_id},user_id.is.null,is_public.eq.true"
    ).execute()

    item_map = {}
    for item in (items_result.data or []):
        item_map[item["id"]] = item

    # Load recipe edges
    edges_result = client.table(TABLES["recipe_edges"]).select("*").or_(
        f"user_id.eq.{user_id},user_id.is.null,is_public.eq.true"
    ).execute()

    edges_by_parent = {}
    for edge in (edges_result.data or []):
        parent_id = edge["parent_food_item_id"]
        if parent_id not in edges_by_parent:
            edges_by_parent[parent_id] = []
        edges_by_parent[parent_id].append(edge)

    # Sort edges by sort_order
    for edges in edges_by_parent.values():
        edges.sort(key=lambda e: e.get("sort_order") or 0)

    # Load recipe nodes (for base_serving_g in proportional recipes)
    nodes_result = client.table(TABLES["recipe_nodes"]).select("*").or_(
        f"user_id.eq.{user_id},user_id.is.null,is_public.eq.true"
    ).execute()

    node_map = {}
    for node in (nodes_result.data or []):
        node_map[node["food_item_id"]] = node

    # Load canonical ingredients (global)
    canonical_map = {}
    try:
        canonicals_result = client.table("foodos2_canonical_ingredients").select("*").execute()
        for c in (canonicals_result.data or []):
            canonical_map[c["id"]] = c
    except Exception as e:
        logger.warning(f"Failed to load canonical ingredients: {e}")

    # Load user's ingredient preferences
    preference_map = {}
    try:
        prefs_result = client.table("foodos2_user_ingredient_preferences").select("*").eq(
            "user_id", user_id
        ).execute()
        for p in (prefs_result.data or []):
            preference_map[p["canonical_id"]] = p
    except Exception as e:
        logger.warning(f"Failed to load ingredient preferences: {e}")

    return RecipeGraphContext(
        item_map=item_map,
        edges_by_parent=edges_by_parent,
        node_map=node_map,
        canonical_map=canonical_map,
        preference_map=preference_map,
    )


def _resolve_canonical(
    canonical_id: str,
    ctx: RecipeGraphContext
) -> Optional[tuple[dict, bool]]:
    """Resolve a canonical ingredient to a FoodItem.

    Returns (item, is_user_preference) or None if not found.
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
        "scaling_mode": "fixed",
        "is_premade": False,
        "notes": canonical.get("description"),
    }
    return (virtual_item, False)


async def flatten_recipe_dag(
    root_food_item_id: str,
    user_id: str,
    scale_factor: float = 1.0,
) -> tuple[dict[str, FlattenedIngredient], bool]:
    """Flatten a recipe DAG into ingredient totals (in grams).

    - Traverses sub-meals recursively.
    - Prevents cycles by tracking the current path.
    - Resolves canonical ingredient references to user's preferred products.

    Returns:
        (ingredients_by_id, cycle_detected)
    """
    ctx = await get_recipe_graph_context(user_id)

    out: dict[str, FlattenedIngredient] = {}
    cycle_detected = False

    def walk(node_id: str, servings: float, path: set[str]):
        nonlocal cycle_detected

        if node_id in path:
            cycle_detected = True
            return

        next_path = path | {node_id}
        node = ctx.item_map.get(node_id)
        if not node:
            return

        children = ctx.edges_by_parent.get(node_id, [])
        if not children:
            # Leaf node - nothing to expand
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

            # Check if this edge uses a canonical ingredient reference
            canonical_id = edge.get("canonical_ingredient_id")
            if canonical_id:
                resolved = _resolve_canonical(canonical_id, ctx)
                if resolved:
                    item, is_user_pref = resolved
                    canonical = ctx.canonical_map.get(canonical_id, {})
                    item_id = item["id"]

                    if item_id in out:
                        out[item_id].amount_g += amount * servings
                    else:
                        out[item_id] = FlattenedIngredient(
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

            if child_kind == "ingredient":
                # Aggregate ingredient amount
                if child_id in out:
                    out[child_id].amount_g += amount * servings
                else:
                    out[child_id] = FlattenedIngredient(
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
                # amount is servings of child per serving of parent
                child_servings = servings * amount
                if child_servings > 0:
                    walk(child_id, child_servings, next_path)

    walk(root_food_item_id, scale_factor, set())

    return out, cycle_detected


def compute_recipe_macros(
    ingredients_by_id: dict[str, FlattenedIngredient]
) -> dict:
    """Compute total and per-100g macros from flattened ingredients."""
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
) -> list[FlattenedIngredient]:
    """Get flattened ingredients for a plan entry (for consumption)."""
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

    if kind == "ingredient" or kind == "product":
        # Direct ingredient/product: scale_factor is GRAMS
        grams = scale_factor if 0 < scale_factor <= 5000 else 100
        return [FlattenedIngredient(
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
    ingredients_by_id, _ = await flatten_recipe_dag(food_item_id, user_id, scale_factor)
    return list(ingredients_by_id.values())
