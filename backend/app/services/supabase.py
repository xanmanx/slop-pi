"""Supabase client service."""

import logging
from functools import lru_cache

from supabase import create_client, Client

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache
def get_supabase_client() -> Client:
    """Get Supabase client with service role key (admin access)."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )


@lru_cache
def get_supabase_anon_client() -> Client:
    """Get Supabase client with anon key (RLS enforced)."""
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
    )


# Table names (match the Next.js app)
TABLES = {
    "prefs": "foodos2_preference_profiles",
    "items": "foodos2_food_items",
    "item_overrides": "foodos2_food_item_overrides",
    "recipe_nodes": "foodos2_recipe_nodes",
    "recipe_edges": "foodos2_recipe_edges",
    "inventory": "foodos2_inventory_items",
    "plan": "foodos2_plan_entries",
    "consumption": "foodos2_inventory_consumption",
    "meal_pools": "foodos2_meal_pools",
    "supplements": "foodos2_supplements",
    "shopping_days": "foodos2_shopping_days",
    "reorders": "foodos2_reorders",
    "batch_prep": "foodos2_batch_prep_instructions",
    "grocery_lists": "grocery_lists",
    "grocery_list_items": "grocery_list_items",
}


async def get_user_prefs(user_id: str) -> dict | None:
    """Get user preference profile."""
    client = get_supabase_client()
    result = client.table(TABLES["prefs"]).select("*").eq("user_id", user_id).single().execute()
    return result.data


async def get_plan_entries(user_id: str, start_date: str, end_date: str) -> list[dict]:
    """Get plan entries for a date range."""
    client = get_supabase_client()
    result = (
        client.table(TABLES["plan"])
        .select("*, food_item:foodos2_food_items(*)")
        .eq("user_id", user_id)
        .gte("planned_date", start_date)
        .lte("planned_date", end_date)
        .order("planned_date")
        .order("slot")
        .execute()
    )
    return result.data or []


async def get_upcoming_meals(user_id: str, date: str, slot: str | None = None) -> list[dict]:
    """Get upcoming meals for reminders."""
    client = get_supabase_client()
    query = (
        client.table(TABLES["plan"])
        .select("*, food_item:foodos2_food_items(name)")
        .eq("user_id", user_id)
        .eq("planned_date", date)
    )
    if slot:
        query = query.eq("slot", slot)
    result = query.execute()
    return result.data or []


async def mark_meal_consumed(entry_id: str, is_logged: bool = True) -> bool:
    """Mark a plan entry as consumed/logged."""
    client = get_supabase_client()
    result = (
        client.table(TABLES["plan"])
        .update({"is_logged": is_logged})
        .eq("id", entry_id)
        .execute()
    )
    return bool(result.data)


async def upsert_food_items(items: list[dict]) -> int:
    """Upsert food items (for USDA imports)."""
    client = get_supabase_client()
    result = (
        client.table(TABLES["items"])
        .upsert(items, on_conflict="kind,source,source_id")
        .execute()
    )
    return len(result.data or [])


async def get_all_users() -> list[dict]:
    """Get all users (for cron jobs that process all users)."""
    client = get_supabase_client()
    result = client.table(TABLES["prefs"]).select("user_id").execute()
    return result.data or []
