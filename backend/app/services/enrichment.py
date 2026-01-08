"""
USDA FoodData Central enrichment service.

Automatically enriches ingredients missing micronutrient data
when they're loaded for recipe flattening.
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)

USDA_API_KEY = os.environ.get("USDA_API_KEY")
USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# Macro nutrient IDs to exclude from micronutrients
MACRO_IDS = {1008, 1003, 1004, 1005}  # kcal, protein, fat, carbs


def _to_mg(amount: float, unit: str) -> Optional[float]:
    """Convert nutrient amount to milligrams."""
    u = unit.lower().strip()
    if u == "mg":
        return amount
    if u in ("µg", "ug", "mcg"):
        return amount / 1000
    if u == "g":
        return amount * 1000
    return None


def _extract_micronutrients(nutrients: list, limit: int = 20) -> list:
    """Extract micronutrients from USDA nutrient list."""
    micros = []

    for n in nutrients:
        nid = n.get("nutrientId") or n.get("nutrient", {}).get("id")
        if not nid or nid in MACRO_IDS:
            continue

        value = n.get("value") or n.get("amount") or 0
        if value <= 0:
            continue

        name = n.get("nutrientName") or n.get("nutrient", {}).get("name") or f"nutrient_{nid}"
        unit = n.get("unitName") or n.get("nutrient", {}).get("unitName") or "mg"

        mg = _to_mg(value, unit)
        micros.append({
            "nutrient_id": nid,
            "name": name,
            "unit": unit,
            "amount_per_100g": round(value, 4),
            "amount_mg_per_100g": round(mg, 6) if mg is not None else None,
        })

    # Sort by mg amount (higher first), nulls last
    micros.sort(key=lambda x: (x["amount_mg_per_100g"] is None, -(x["amount_mg_per_100g"] or 0)))

    return micros[:limit]


async def search_usda(query: str, limit: int = 3) -> Optional[dict]:
    """Search USDA for a food by name."""
    if not USDA_API_KEY:
        logger.warning("USDA_API_KEY not set, skipping enrichment")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{USDA_BASE_URL}/foods/search",
                params={"api_key": USDA_API_KEY},
                json={
                    "query": query,
                    "pageSize": limit,
                    "pageNumber": 1,
                    "dataType": ["Foundation", "SR Legacy"],
                    "requireAllWords": False,
                }
            )

            if resp.status_code != 200:
                logger.warning(f"USDA search failed: {resp.status_code}")
                return None

            data = resp.json()
            foods = data.get("foods", [])

            # Prefer Foundation or SR Legacy
            for f in foods:
                if f.get("dataType") in ("Foundation", "SR Legacy"):
                    return f

            return foods[0] if foods else None
    except Exception as e:
        logger.error(f"USDA search error: {e}")
        return None


async def get_usda_food(fdc_id: int) -> Optional[dict]:
    """Get full nutrient data for a specific FDC ID."""
    if not USDA_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{USDA_BASE_URL}/food/{fdc_id}",
                params={"api_key": USDA_API_KEY}
            )

            if resp.status_code != 200:
                return None

            return resp.json()
    except Exception as e:
        logger.error(f"USDA fetch error: {e}")
        return None


async def enrich_ingredient(ingredient_id: str, ingredient_name: str, usda_fdc_id: Optional[int] = None) -> bool:
    """Enrich a single ingredient with USDA micronutrients.

    Returns True if enrichment was successful.
    """
    client = get_supabase_client()

    # If we have a FDC ID, use it directly
    if usda_fdc_id:
        food = await get_usda_food(usda_fdc_id)
        if food:
            nutrients = food.get("foodNutrients", [])
            micros = _extract_micronutrients(nutrients)

            if micros:
                try:
                    client.table(TABLES["items"]).update({
                        "micronutrients": micros
                    }).eq("id", ingredient_id).execute()
                    logger.info(f"Enriched '{ingredient_name}' with {len(micros)} micronutrients (FDC: {usda_fdc_id})")
                    return True
                except Exception as e:
                    logger.error(f"Failed to update ingredient {ingredient_id}: {e}")

    # Search USDA by name
    match = await search_usda(ingredient_name)
    if not match:
        logger.debug(f"No USDA match for '{ingredient_name}'")
        return False

    fdc_id = match.get("fdcId")
    if not fdc_id:
        return False

    # Get full nutrient data
    food = await get_usda_food(fdc_id)
    if not food:
        return False

    nutrients = food.get("foodNutrients", [])
    micros = _extract_micronutrients(nutrients)

    if not micros:
        return False

    # Update the ingredient
    try:
        client.table(TABLES["items"]).update({
            "micronutrients": micros,
            "usda_fdc_id": fdc_id
        }).eq("id", ingredient_id).execute()
        logger.info(f"Enriched '{ingredient_name}' with {len(micros)} micronutrients (matched: {food.get('description', 'unknown')})")
        return True
    except Exception as e:
        logger.error(f"Failed to update ingredient {ingredient_id}: {e}")
        return False


async def enrich_ingredients_batch(ingredients: list[dict]) -> int:
    """Enrich multiple ingredients in parallel.

    Args:
        ingredients: List of dicts with 'id', 'name', 'micronutrients', 'usda_fdc_id'

    Returns:
        Number of successfully enriched ingredients.
    """
    # Filter to only those missing micronutrients
    to_enrich = [
        ing for ing in ingredients
        if not ing.get("micronutrients") or ing.get("micronutrients") == []
    ]

    if not to_enrich:
        return 0

    logger.info(f"Enriching {len(to_enrich)} ingredients missing micronutrients...")

    # Process in batches of 5 to avoid rate limiting
    enriched_count = 0
    for i in range(0, len(to_enrich), 5):
        batch = to_enrich[i:i+5]

        tasks = [
            enrich_ingredient(
                ing["id"],
                ing.get("name", "unknown"),
                ing.get("usda_fdc_id")
            )
            for ing in batch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        enriched_count += sum(1 for r in results if r is True)

        # Rate limit delay between batches
        if i + 5 < len(to_enrich):
            await asyncio.sleep(0.2)

    logger.info(f"Enriched {enriched_count}/{len(to_enrich)} ingredients")
    return enriched_count


async def ensure_ingredients_enriched(item_map: dict) -> dict:
    """Check all ingredients in item_map and enrich any missing micronutrients.

    This is called during recipe graph loading to ensure nutrition data is complete.

    Args:
        item_map: Dict of id -> FoodItem

    Returns:
        Updated item_map with enriched micronutrients
    """
    if not USDA_API_KEY:
        return item_map

    # Find ingredients missing micronutrients
    to_enrich = []
    for item_id, item in item_map.items():
        if item.get("kind") != "ingredient":
            continue

        micros = item.get("micronutrients")
        if not micros or micros == []:
            to_enrich.append({
                "id": item_id,
                "name": item.get("name", "unknown"),
                "usda_fdc_id": item.get("usda_fdc_id"),
            })

    if not to_enrich:
        return item_map

    # Enrich in background - don't block the request
    # The enrichment will happen async and be available on next request
    logger.info(f"Scheduling background enrichment for {len(to_enrich)} ingredients")
    asyncio.create_task(_enrich_background(to_enrich))

    return item_map


async def _enrich_background(to_enrich: list[dict]) -> None:
    """Background task to enrich ingredients without blocking requests."""
    try:
        enriched_count = await enrich_ingredients_batch(to_enrich)
        logger.info(f"Background enrichment complete: {enriched_count}/{len(to_enrich)} enriched")
    except Exception as e:
        logger.error(f"Background enrichment failed: {e}")
