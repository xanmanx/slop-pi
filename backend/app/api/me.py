"""
Simple text endpoints for Claude mobile/web access.

These endpoints return plain text summaries that Claude can easily read.
Only accessible from local network (192.168.x.x).
"""

from datetime import date, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.supabase import get_supabase
from app.services.recipe_graph import RecipeGraphService
from app.services.nutrition import compute_daily_nutrition

router = APIRouter(prefix="/me", tags=["me"])

# Hardcoded user ID for local access (your account)
DEFAULT_USER_ID = "b7ddfbbd-58c0-4076-9406-58dd1930aee5"


def check_local_network(request: Request):
    """Ensure request is from local network only."""
    client_ip = request.client.host if request.client else ""

    # Allow local IPs: 192.168.x.x, 10.x.x.x, 172.16-31.x.x, localhost
    local_prefixes = ("192.168.", "10.", "172.16.", "172.17.", "172.18.",
                      "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                      "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                      "172.29.", "172.30.", "172.31.", "127.", "::1", "localhost")

    if not any(client_ip.startswith(prefix) for prefix in local_prefixes):
        raise HTTPException(status_code=403, detail="Local network access only")


@router.get("/today", response_class=PlainTextResponse)
async def today_summary(request: Request):
    """Get today's meal plan, nutrition, and expiring items."""
    check_local_network(request)

    supabase = get_supabase()
    today = date.today().isoformat()
    lines = [f"# Today ({today})", ""]

    # 1. Meal Plan
    result = (
        supabase.table("foodos2_plan_entries")
        .select("slot, scale_factor, foodos2_food_items(name, kind)")
        .eq("user_id", DEFAULT_USER_ID)
        .eq("planned_date", today)
        .order("slot")
        .execute()
    )

    lines.append("## Meals")
    if result.data:
        slot_order = {"breakfast": 1, "lunch": 2, "dinner": 3, "snack": 4}
        entries = sorted(result.data, key=lambda x: slot_order.get(x["slot"], 5))
        for entry in entries:
            food = entry.get("foodos2_food_items", {})
            name = food.get("name", "Unknown") if food else "Unknown"
            slot = entry["slot"].title()
            scale = entry.get("scale_factor", 1)
            scale_str = f" (x{scale:.1f})" if scale != 1 else ""
            lines.append(f"- {slot}: {name}{scale_str}")
    else:
        lines.append("- No meals planned")
    lines.append("")

    # 2. Nutrition
    try:
        graph_service = RecipeGraphService(DEFAULT_USER_ID)
        nutrition = await compute_daily_nutrition(
            DEFAULT_USER_ID, today, graph_service,
            include_supplements=True, include_planned=True
        )

        n = nutrition.get("nutrition", {})
        target = nutrition.get("target_calories", 0)
        actual = n.get("calories", 0)

        lines.append("## Nutrition")
        lines.append(f"- Calories: {actual:.0f} / {target:.0f} kcal")
        lines.append(f"- Protein: {n.get('protein_g', 0):.0f}g")
        lines.append(f"- Carbs: {n.get('carbs_g', 0):.0f}g")
        lines.append(f"- Fat: {n.get('fat_g', 0):.0f}g")

        v_score = nutrition.get("vitamin_score")
        m_score = nutrition.get("mineral_score")
        if v_score is not None:
            lines.append(f"- Vitamins: {v_score:.0f}% | Minerals: {m_score:.0f}%")
    except Exception as e:
        lines.append("## Nutrition")
        lines.append(f"- Error loading: {e}")
    lines.append("")

    # 3. Expiring Items
    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, foodos2_food_items(name)")
        .eq("user_id", DEFAULT_USER_ID)
        .not_.is_("expiration_date", "null")
        .lte("expiration_date", (date.today() + timedelta(days=3)).isoformat())
        .order("expiration_date")
        .execute()
    )

    if result.data:
        lines.append("## Expiring Soon (3 days)")
        for item in result.data:
            food = item.get("foodos2_food_items", {})
            name = food.get("name", "Unknown") if food else "Unknown"
            qty = item.get("quantity_g", 0)
            exp = item.get("expiration_date", "")
            days_left = (date.fromisoformat(exp) - date.today()).days if exp else 0

            if days_left < 0:
                exp_str = "EXPIRED"
            elif days_left == 0:
                exp_str = "TODAY"
            else:
                exp_str = f"{days_left}d"
            lines.append(f"- {name}: {qty:.0f}g ({exp_str})")
        lines.append("")

    return "\n".join(lines)


@router.get("/week", response_class=PlainTextResponse)
async def week_summary(request: Request):
    """Get this week's meal plan and grocery list summary."""
    check_local_network(request)

    supabase = get_supabase()
    today = date.today()
    week_end = today + timedelta(days=6)

    lines = [f"# Week ({today.isoformat()} to {week_end.isoformat()})", ""]

    # Meal Plan
    result = (
        supabase.table("foodos2_plan_entries")
        .select("planned_date, slot, foodos2_food_items(name)")
        .eq("user_id", DEFAULT_USER_ID)
        .gte("planned_date", today.isoformat())
        .lte("planned_date", week_end.isoformat())
        .order("planned_date")
        .order("slot")
        .execute()
    )

    lines.append("## Meal Plan")
    if result.data:
        by_date = {}
        for entry in result.data:
            d = entry["planned_date"]
            if d not in by_date:
                by_date[d] = []
            food = entry.get("foodos2_food_items", {})
            name = food.get("name", "?") if food else "?"
            by_date[d].append(f"{entry['slot'][0].upper()}: {name}")

        for d in sorted(by_date.keys()):
            day_name = date.fromisoformat(d).strftime("%a %m/%d")
            meals = " | ".join(by_date[d])
            lines.append(f"- {day_name}: {meals}")
    else:
        lines.append("- No meals planned")
    lines.append("")

    # Quick inventory summary
    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, foodos2_food_items(name)")
        .eq("user_id", DEFAULT_USER_ID)
        .gt("quantity_g", 0)
        .execute()
    )

    lines.append(f"## Inventory ({len(result.data)} items)")
    if result.data:
        # Show top items by quantity
        items = sorted(result.data, key=lambda x: x.get("quantity_g", 0), reverse=True)[:10]
        for item in items:
            food = item.get("foodos2_food_items", {})
            name = food.get("name", "?") if food else "?"
            qty = item.get("quantity_g", 0)
            lines.append(f"- {name}: {qty:.0f}g")
    lines.append("")

    return "\n".join(lines)


@router.get("/inventory", response_class=PlainTextResponse)
async def inventory_summary(request: Request):
    """Get current inventory."""
    check_local_network(request)

    supabase = get_supabase()
    today = date.today()

    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, storage_type, foodos2_food_items(name)")
        .eq("user_id", DEFAULT_USER_ID)
        .gt("quantity_g", 0)
        .order("expiration_date")
        .execute()
    )

    lines = [f"# Inventory ({len(result.data)} items)", ""]

    if not result.data:
        lines.append("Empty")
        return "\n".join(lines)

    # Group by storage
    by_storage = {"refrigerator": [], "freezer": [], "pantry": [], "other": []}
    for item in result.data:
        storage = item.get("storage_type", "other") or "other"
        if storage not in by_storage:
            storage = "other"
        by_storage[storage].append(item)

    for storage, items in by_storage.items():
        if not items:
            continue
        lines.append(f"## {storage.title()}")
        for item in items:
            food = item.get("foodos2_food_items", {})
            name = food.get("name", "?") if food else "?"
            qty = item.get("quantity_g", 0)
            exp = item.get("expiration_date")

            exp_str = ""
            if exp:
                days = (date.fromisoformat(exp) - today).days
                if days < 0:
                    exp_str = " [EXPIRED]"
                elif days == 0:
                    exp_str = " [TODAY]"
                elif days <= 3:
                    exp_str = f" [{days}d]"

            lines.append(f"- {name}: {qty:.0f}g{exp_str}")
        lines.append("")

    return "\n".join(lines)


@router.get("/recipes", response_class=PlainTextResponse)
async def recipes_list(request: Request, q: str = ""):
    """Search recipes or list recent ones."""
    check_local_network(request)

    supabase = get_supabase()

    query = (
        supabase.table("foodos2_food_items")
        .select("name, kind, calories_per_100g, protein_g_per_100g")
        .eq("user_id", DEFAULT_USER_ID)
        .in_("kind", ["meal", "snack"])
        .limit(20)
    )

    if q:
        query = query.ilike("name", f"%{q}%")

    result = query.execute()

    lines = [f"# Recipes" + (f" matching '{q}'" if q else ""), ""]

    if result.data:
        for item in result.data:
            name = item["name"]
            cal = item.get("calories_per_100g") or 0
            protein = item.get("protein_g_per_100g") or 0
            lines.append(f"- {name} ({cal:.0f} cal, {protein:.0f}g protein per 100g)")
    else:
        lines.append("No recipes found")

    return "\n".join(lines)
