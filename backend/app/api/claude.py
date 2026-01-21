"""
Claude API endpoints - Token-authenticated access for AI assistants.

These endpoints allow users to give their AI (Claude, ChatGPT, etc.) access to their
meal planning data via a personal API token generated in settings.

URL Pattern: /claude/{token}/{action}

Features:
- Token-based authentication (no user context needed)
- Plain text responses optimized for AI readability
- Usage tracking (last_used_at updated on each request)
- Comprehensive meal planning, inventory, and nutrition access

Security:
- Tokens are user-generated and can be revoked anytime
- Each token is tied to a single user
- RLS ensures data isolation
"""

import secrets
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.services.supabase import get_supabase
from app.services.recipe_graph import RecipeGraphService
from app.services.nutrition import compute_daily_nutrition

router = APIRouter(prefix="/claude", tags=["claude"])


# =============================================================================
# AUTH HELPERS
# =============================================================================

async def get_user_from_token(token: str) -> dict:
    """
    Validate token and return user info.
    Updates last_used_at timestamp.

    Returns:
        {"user_id": str, "token_id": str, "name": str}

    Raises:
        HTTPException 401 if token invalid/inactive
    """
    supabase = get_supabase()

    result = (
        supabase.table("foodos2_api_tokens")
        .select("id, user_id, name")
        .eq("token", token)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid or inactive token")

    token_data = result.data[0]

    # Update last_used_at (fire and forget)
    try:
        supabase.table("foodos2_api_tokens").update({
            "last_used_at": "now()"
        }).eq("id", token_data["id"]).execute()
    except Exception:
        pass  # Don't fail request if usage tracking fails

    return {
        "user_id": token_data["user_id"],
        "token_id": token_data["id"],
        "name": token_data.get("name", "User"),
    }


def format_quantity(grams: float) -> str:
    """Format grams into human-readable units."""
    if grams >= 1000:
        return f"{grams/1000:.1f}kg"
    elif grams >= 454:
        lbs = grams / 454
        return f"{lbs:.1f}lbs" if lbs != int(lbs) else f"{int(lbs)}lbs"
    else:
        return f"{grams:.0f}g"


# =============================================================================
# INFO - API documentation
# =============================================================================

@router.get("/{token}", response_class=PlainTextResponse)
async def api_info(token: str):
    """
    Get API info and available commands.
    Use this to verify your token works and see what you can do.
    """
    user = await get_user_from_token(token)

    return f"""# Slop API - Connected!

Welcome! Your token is valid and connected to your meal planning account.

## Available Commands

Replace {{token}} with your token in all URLs.

### Daily Overview
GET /claude/{{token}}/today
  - Today's meals, nutrition, and expiring items

### Meal Planning
GET /claude/{{token}}/meals?days=7
  - View planned meals (default: 7 days)

GET /claude/{{token}}/plan?meal=chicken+stir+fry&slot=dinner&day=2024-01-21
  - Add meal to plan (slot: breakfast/lunch/dinner/snack)

### Nutrition
GET /claude/{{token}}/nutrition?day=2024-01-20
  - Detailed nutrition for a specific day

### Inventory
GET /claude/{{token}}/inventory
  - View all inventory items

GET /claude/{{token}}/add?item=ground+beef&qty=454&storage=refrigerator&expires=2024-01-25
  - Add item to inventory (qty in grams, 454g = 1lb)

GET /claude/{{token}}/use?item=ground+beef&qty=200
  - Use/subtract from inventory

GET /claude/{{token}}/expiring?days=3
  - Items expiring soon

### Grocery
GET /claude/{{token}}/grocery?days=7
  - Generate grocery list for upcoming days

GET /claude/{{token}}/bought?days=7
  - Mark grocery list as purchased (adds to inventory)

### Recipes
GET /claude/{{token}}/recipes?q=chicken
  - Search your recipes

GET /claude/{{token}}/recipe?name=chicken+stir+fry
  - Get full recipe details with ingredients

## Tips
- All quantities are in grams (454g = 1lb, 28g = 1oz)
- Dates use YYYY-MM-DD format
- URL encode spaces as + or %20
- Responses are plain text for easy AI parsing
"""


# =============================================================================
# TODAY - Daily summary
# =============================================================================

@router.get("/{token}/today", response_class=PlainTextResponse)
async def today_summary(token: str):
    """Get today's meal plan, nutrition summary, and expiring items."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()
    today = date.today()
    today_str = today.isoformat()

    lines = [f"# Today ({today_str})", ""]

    # 1. Meal Plan
    result = (
        supabase.table("foodos2_plan_entries")
        .select("slot, scale_factor, foodos2_food_items(name, kind, calories_per_100g, protein_g_per_100g)")
        .eq("user_id", user_id)
        .eq("planned_date", today_str)
        .order("slot")
        .execute()
    )

    lines.append("## Meals Planned")
    if result.data:
        slot_order = {"breakfast": 1, "lunch": 2, "dinner": 3, "snack": 4}
        entries = sorted(result.data, key=lambda x: slot_order.get(x["slot"], 5))

        total_cal = 0
        total_protein = 0

        for entry in entries:
            food = entry.get("foodos2_food_items", {}) or {}
            name = food.get("name", "Unknown")
            slot = entry["slot"].title()
            scale = entry.get("scale_factor", 1) or 1
            cal = (food.get("calories_per_100g") or 0) * scale
            protein = (food.get("protein_g_per_100g") or 0) * scale

            total_cal += cal
            total_protein += protein

            scale_str = f" (x{scale:.1f})" if scale != 1 else ""
            lines.append(f"- {slot}: {name}{scale_str}")

        lines.append("")
        lines.append(f"Estimated: ~{total_cal:.0f} cal, ~{total_protein:.0f}g protein")
    else:
        lines.append("- No meals planned yet")
    lines.append("")

    # 2. Full Nutrition (computed)
    try:
        graph_service = RecipeGraphService(user_id)
        nutrition = await compute_daily_nutrition(
            user_id, today_str, graph_service,
            include_supplements=True, include_planned=True
        )

        n = nutrition.get("nutrition", {})
        target = nutrition.get("target_calories", 2000)
        actual = n.get("calories", 0)

        lines.append("## Nutrition Summary")
        pct = (actual / target * 100) if target > 0 else 0
        lines.append(f"- Calories: {actual:.0f} / {target:.0f} ({pct:.0f}%)")
        lines.append(f"- Protein: {n.get('protein_g', 0):.0f}g")
        lines.append(f"- Carbs: {n.get('carbs_g', 0):.0f}g")
        lines.append(f"- Fat: {n.get('fat_g', 0):.0f}g")
        lines.append(f"- Fiber: {n.get('fiber_g', 0):.0f}g")

        v_score = nutrition.get("vitamin_score")
        m_score = nutrition.get("mineral_score")
        if v_score is not None:
            lines.append(f"- Micronutrients: {v_score:.0f}% vitamins, {m_score:.0f}% minerals")
    except Exception as e:
        lines.append("## Nutrition Summary")
        lines.append(f"- Could not compute: {e}")
    lines.append("")

    # 3. Expiring Items (next 3 days)
    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .gt("quantity_g", 0)
        .not_.is_("expiration_date", "null")
        .lte("expiration_date", (today + timedelta(days=3)).isoformat())
        .order("expiration_date")
        .execute()
    )

    if result.data:
        lines.append("## Expiring Soon (use these up!)")
        for item in result.data:
            food = item.get("foodos2_food_items", {}) or {}
            name = food.get("name", "Unknown")
            qty = item.get("quantity_g", 0)
            exp = item.get("expiration_date", "")

            if exp:
                days_left = (date.fromisoformat(exp) - today).days
                if days_left < 0:
                    exp_str = "EXPIRED"
                elif days_left == 0:
                    exp_str = "TODAY"
                elif days_left == 1:
                    exp_str = "tomorrow"
                else:
                    exp_str = f"in {days_left} days"
            else:
                exp_str = ""

            lines.append(f"- {name}: {format_quantity(qty)} (expires {exp_str})")

    return "\n".join(lines)


# =============================================================================
# MEALS - View meal plan
# =============================================================================

@router.get("/{token}/meals", response_class=PlainTextResponse)
async def get_meals(
    token: str,
    days: int = Query(7, ge=1, le=30, description="Number of days to show"),
):
    """Get planned meals for the next N days."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()
    today = date.today()
    end_date = today + timedelta(days=days - 1)

    result = (
        supabase.table("foodos2_plan_entries")
        .select("planned_date, slot, scale_factor, foodos2_food_items(name, kind)")
        .eq("user_id", user_id)
        .gte("planned_date", today.isoformat())
        .lte("planned_date", end_date.isoformat())
        .order("planned_date")
        .order("slot")
        .execute()
    )

    lines = [f"# Meal Plan ({today.isoformat()} to {end_date.isoformat()})", ""]

    if not result.data:
        lines.append("No meals planned for this period.")
        return "\n".join(lines)

    # Group by date
    by_date = {}
    for entry in result.data:
        d = entry["planned_date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(entry)

    slot_order = {"breakfast": 1, "lunch": 2, "dinner": 3, "snack": 4}

    for d in sorted(by_date.keys()):
        day_date = date.fromisoformat(d)
        day_name = day_date.strftime("%A")
        is_today = day_date == today

        lines.append(f"## {day_name} ({d})" + (" - TODAY" if is_today else ""))

        entries = sorted(by_date[d], key=lambda x: slot_order.get(x["slot"], 5))
        for entry in entries:
            food = entry.get("foodos2_food_items", {}) or {}
            name = food.get("name", "Unknown")
            slot = entry["slot"].title()
            scale = entry.get("scale_factor", 1)
            scale_str = f" (x{scale:.1f})" if scale and scale != 1 else ""
            lines.append(f"- {slot}: {name}{scale_str}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# NUTRITION - Detailed nutrition for a day
# =============================================================================

@router.get("/{token}/nutrition", response_class=PlainTextResponse)
async def get_nutrition(
    token: str,
    day: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
):
    """Get detailed nutrition breakdown for a specific day."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    target_date = day or date.today().isoformat()

    try:
        graph_service = RecipeGraphService(user_id)
        nutrition = await compute_daily_nutrition(
            user_id, target_date, graph_service,
            include_supplements=True, include_planned=True
        )
    except Exception as e:
        return f"Error computing nutrition: {e}"

    n = nutrition.get("nutrition", {})
    target = nutrition.get("target_calories", 2000)

    lines = [f"# Nutrition for {target_date}", ""]

    # Macros
    lines.append("## Macros")
    cal = n.get("calories", 0)
    pct = (cal / target * 100) if target > 0 else 0
    lines.append(f"- Calories: {cal:.0f} / {target:.0f} kcal ({pct:.0f}%)")
    lines.append(f"- Protein: {n.get('protein_g', 0):.1f}g")
    lines.append(f"- Carbohydrates: {n.get('carbs_g', 0):.1f}g")
    lines.append(f"- Fat: {n.get('fat_g', 0):.1f}g")
    lines.append(f"- Fiber: {n.get('fiber_g', 0):.1f}g")
    lines.append(f"- Sugar: {n.get('sugar_g', 0):.1f}g")
    lines.append(f"- Sodium: {n.get('sodium_mg', 0):.0f}mg")
    lines.append("")

    # Micronutrient scores
    v_score = nutrition.get("vitamin_score")
    m_score = nutrition.get("mineral_score")
    if v_score is not None:
        lines.append("## Micronutrient Coverage")
        lines.append(f"- Vitamin Score: {v_score:.0f}% of RDA")
        lines.append(f"- Mineral Score: {m_score:.0f}% of RDA")
        lines.append("")

    # Detailed vitamins
    vitamins = nutrition.get("vitamins", {})
    if vitamins:
        lines.append("## Vitamins (amount / RDA%)")
        for name, data in sorted(vitamins.items()):
            if isinstance(data, dict):
                amt = data.get("amount", 0)
                pct = data.get("rda_pct", 0)
                unit = data.get("unit", "")
                lines.append(f"- {name}: {amt:.1f}{unit} ({pct:.0f}%)")
        lines.append("")

    # Detailed minerals
    minerals = nutrition.get("minerals", {})
    if minerals:
        lines.append("## Minerals (amount / RDA%)")
        for name, data in sorted(minerals.items()):
            if isinstance(data, dict):
                amt = data.get("amount", 0)
                pct = data.get("rda_pct", 0)
                unit = data.get("unit", "")
                lines.append(f"- {name}: {amt:.1f}{unit} ({pct:.0f}%)")

    return "\n".join(lines)


# =============================================================================
# INVENTORY - View and manage inventory
# =============================================================================

@router.get("/{token}/inventory", response_class=PlainTextResponse)
async def get_inventory(token: str):
    """Get current inventory grouped by storage location."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()
    today = date.today()

    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, storage_type, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .gt("quantity_g", 0)
        .order("expiration_date")
        .execute()
    )

    lines = [f"# Inventory ({len(result.data)} items)", ""]

    if not result.data:
        lines.append("Inventory is empty.")
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

        emoji = {"refrigerator": "🧊", "freezer": "❄️", "pantry": "🏠"}.get(storage, "📦")
        lines.append(f"## {emoji} {storage.title()} ({len(items)} items)")

        for item in items:
            food = item.get("foodos2_food_items", {}) or {}
            name = food.get("name", "Unknown")
            qty = item.get("quantity_g", 0)
            exp = item.get("expiration_date")

            exp_str = ""
            if exp:
                days = (date.fromisoformat(exp) - today).days
                if days < 0:
                    exp_str = " ⚠️ EXPIRED"
                elif days == 0:
                    exp_str = " ⚠️ expires TODAY"
                elif days <= 3:
                    exp_str = f" ⚠️ expires in {days}d"
                elif days <= 7:
                    exp_str = f" (expires in {days}d)"

            lines.append(f"- {name}: {format_quantity(qty)}{exp_str}")
        lines.append("")

    return "\n".join(lines)


@router.get("/{token}/add", response_class=PlainTextResponse)
async def add_to_inventory(
    token: str,
    item: str = Query(..., description="Food item name"),
    qty: float = Query(..., description="Quantity in grams (454 = 1lb)"),
    storage: str = Query("refrigerator", description="Storage: refrigerator/freezer/pantry"),
    expires: Optional[str] = Query(None, description="Expiration date YYYY-MM-DD"),
):
    """Add an item to inventory."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()

    # Find existing food item
    result = (
        supabase.table("foodos2_food_items")
        .select("id, name")
        .eq("user_id", user_id)
        .ilike("name", f"%{item}%")
        .limit(1)
        .execute()
    )

    if result.data:
        food_item_id = result.data[0]["id"]
        food_name = result.data[0]["name"]
    else:
        # Create new ingredient
        new_item = {
            "user_id": user_id,
            "name": item,
            "kind": "ingredient",
            "calories_per_100g": 0,
            "protein_g_per_100g": 0,
            "carbs_g_per_100g": 0,
            "fat_g_per_100g": 0,
        }
        result = supabase.table("foodos2_food_items").insert(new_item).execute()
        food_item_id = result.data[0]["id"]
        food_name = item

    # Check if already in inventory
    existing = (
        supabase.table("foodos2_inventory_items")
        .select("id, quantity_g")
        .eq("user_id", user_id)
        .eq("food_item_id", food_item_id)
        .limit(1)
        .execute()
    )

    if existing.data:
        # Update existing
        old_qty = float(existing.data[0]["quantity_g"])
        new_qty = old_qty + qty
        update_data = {"quantity_g": new_qty}
        if expires:
            update_data["expiration_date"] = expires
        supabase.table("foodos2_inventory_items").update(update_data).eq("id", existing.data[0]["id"]).execute()
        return f"Updated {food_name}: {format_quantity(old_qty)} + {format_quantity(qty)} = {format_quantity(new_qty)}"
    else:
        # Add new
        inventory_item = {
            "user_id": user_id,
            "food_item_id": food_item_id,
            "quantity_g": qty,
            "date_added": date.today().isoformat(),
            "storage_type": storage,
        }
        if expires:
            inventory_item["expiration_date"] = expires

        supabase.table("foodos2_inventory_items").insert(inventory_item).execute()

        exp_str = f", expires {expires}" if expires else ""
        return f"Added {format_quantity(qty)} of {food_name} to {storage}{exp_str}"


@router.get("/{token}/use", response_class=PlainTextResponse)
async def use_from_inventory(
    token: str,
    item: str = Query(..., description="Food item name"),
    qty: float = Query(..., description="Quantity in grams to use"),
):
    """Use (subtract) quantity from an inventory item."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()

    # Find inventory item
    result = (
        supabase.table("foodos2_inventory_items")
        .select("id, quantity_g, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .gt("quantity_g", 0)
        .execute()
    )

    matching = None
    for inv_item in result.data:
        food = inv_item.get("foodos2_food_items", {}) or {}
        name = food.get("name", "")
        if item.lower() in name.lower():
            matching = inv_item
            break

    if not matching:
        return f"Could not find '{item}' in inventory"

    old_qty = float(matching["quantity_g"])
    new_qty = max(0, old_qty - qty)

    supabase.table("foodos2_inventory_items").update({
        "quantity_g": new_qty
    }).eq("id", matching["id"]).execute()

    food_name = matching.get("foodos2_food_items", {}).get("name", item)

    if new_qty == 0:
        return f"Used all remaining {food_name} ({format_quantity(old_qty)}). Item is now empty."
    else:
        return f"Used {format_quantity(qty)} of {food_name}. Remaining: {format_quantity(new_qty)}"


@router.get("/{token}/expiring", response_class=PlainTextResponse)
async def get_expiring(
    token: str,
    days: int = Query(3, ge=1, le=14, description="Days to look ahead"),
):
    """Get items expiring within N days."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()
    today = date.today()
    cutoff = today + timedelta(days=days)

    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, storage_type, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .gt("quantity_g", 0)
        .not_.is_("expiration_date", "null")
        .lte("expiration_date", cutoff.isoformat())
        .order("expiration_date")
        .execute()
    )

    lines = [f"# Items Expiring Within {days} Days", ""]

    if not result.data:
        lines.append("Nothing expiring soon!")
        return "\n".join(lines)

    expired = []
    expiring_today = []
    expiring_soon = []

    for item in result.data:
        food = item.get("foodos2_food_items", {}) or {}
        name = food.get("name", "Unknown")
        qty = item.get("quantity_g", 0)
        exp = item.get("expiration_date", "")
        storage = item.get("storage_type", "")

        days_left = (date.fromisoformat(exp) - today).days if exp else 999

        entry = f"- {name}: {format_quantity(qty)} in {storage}"

        if days_left < 0:
            expired.append(f"{entry} (EXPIRED {-days_left}d ago)")
        elif days_left == 0:
            expiring_today.append(f"{entry} (TODAY)")
        else:
            expiring_soon.append(f"{entry} (in {days_left}d)")

    if expired:
        lines.append("## ⚠️ EXPIRED")
        lines.extend(expired)
        lines.append("")

    if expiring_today:
        lines.append("## 🔴 Expires TODAY")
        lines.extend(expiring_today)
        lines.append("")

    if expiring_soon:
        lines.append("## 🟡 Expiring Soon")
        lines.extend(expiring_soon)

    return "\n".join(lines)


# =============================================================================
# GROCERY - Shopping lists
# =============================================================================

@router.get("/{token}/grocery", response_class=PlainTextResponse)
async def get_grocery_list(
    token: str,
    days: int = Query(7, ge=1, le=14, description="Days to plan for"),
):
    """Generate grocery list based on meal plan."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    from app.models.grocery import GroceryGenerationRequest
    from app.services.grocery import generate_grocery_list

    today = date.today()
    end = today + timedelta(days=days - 1)

    try:
        request_obj = GroceryGenerationRequest(
            user_id=user_id,
            start_date=today,
            end_date=end,
            include_meals=True,
            include_reorders=False,
            include_supplements=False,
            subtract_inventory=True,
            group_by_category=True,
            group_similar_items=True,
        )
        grocery_list = await generate_grocery_list(request_obj)

        lines = [f"# Grocery List", ""]
        lines.append(f"For {days} days ({today.isoformat()} to {end.isoformat()})")
        lines.append(f"Items needed: {grocery_list.items_to_buy_count}")
        lines.append("")

        if not grocery_list.items:
            lines.append("Nothing to buy! You have everything you need.")
            return "\n".join(lines)

        # Group by category
        by_category = grocery_list.by_category or {}
        if by_category:
            for category, items in sorted(by_category.items()):
                lines.append(f"## {category}")
                for item in items:
                    name = item.get("name") or item.get("ingredient_name", "?")
                    to_buy = item.get("to_buy_g", 0)
                    if to_buy > 0:
                        lines.append(f"- [ ] {name}: {format_quantity(to_buy)}")
                lines.append("")
        else:
            for item in grocery_list.items:
                if item.to_buy_g > 0:
                    lines.append(f"- [ ] {item.name}: {format_quantity(item.to_buy_g)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating grocery list: {e}"


@router.get("/{token}/bought", response_class=PlainTextResponse)
async def mark_bought(
    token: str,
    days: int = Query(7, ge=1, le=14, description="Days the grocery list was for"),
):
    """Mark grocery list as purchased - adds all items to inventory."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    from app.models.grocery import GroceryGenerationRequest
    from app.services.grocery import generate_grocery_list

    supabase = get_supabase()
    today = date.today()
    end = today + timedelta(days=days - 1)

    try:
        request_obj = GroceryGenerationRequest(
            user_id=user_id,
            start_date=today,
            end_date=end,
            include_meals=True,
            include_reorders=False,
            include_supplements=False,
            subtract_inventory=True,
            group_by_category=True,
        )
        grocery_list = await generate_grocery_list(request_obj)

        if not grocery_list.items:
            return "No items on grocery list to add"

        added = []
        errors = []

        for item in grocery_list.items:
            if item.to_buy_g <= 0:
                continue

            name = item.name
            qty = item.to_buy_g
            ingredient_id = item.ingredient_id

            # Determine storage based on category
            cat = str(item.category.value) if item.category else ""
            if "frozen" in cat.lower():
                storage = "freezer"
            elif "pantry" in cat.lower() or "dry" in cat.lower():
                storage = "pantry"
            else:
                storage = "refrigerator"

            try:
                # Find or create food item
                if ingredient_id:
                    food_item_id = ingredient_id
                else:
                    result = (
                        supabase.table("foodos2_food_items")
                        .select("id")
                        .eq("user_id", user_id)
                        .ilike("name", f"%{name}%")
                        .limit(1)
                        .execute()
                    )
                    if result.data:
                        food_item_id = result.data[0]["id"]
                    else:
                        new_item = {
                            "user_id": user_id,
                            "name": name,
                            "kind": "ingredient",
                            "calories_per_100g": 0,
                            "protein_g_per_100g": 0,
                            "carbs_g_per_100g": 0,
                            "fat_g_per_100g": 0,
                        }
                        result = supabase.table("foodos2_food_items").insert(new_item).execute()
                        food_item_id = result.data[0]["id"]

                # Check if already in inventory
                existing = (
                    supabase.table("foodos2_inventory_items")
                    .select("id, quantity_g")
                    .eq("user_id", user_id)
                    .eq("food_item_id", food_item_id)
                    .limit(1)
                    .execute()
                )

                if existing.data:
                    old_qty = float(existing.data[0]["quantity_g"])
                    new_qty = old_qty + qty
                    supabase.table("foodos2_inventory_items").update({
                        "quantity_g": new_qty
                    }).eq("id", existing.data[0]["id"]).execute()
                else:
                    supabase.table("foodos2_inventory_items").insert({
                        "user_id": user_id,
                        "food_item_id": food_item_id,
                        "quantity_g": qty,
                        "date_added": today.isoformat(),
                        "storage_type": storage,
                    }).execute()

                added.append(f"{name}: {format_quantity(qty)}")

            except Exception as e:
                errors.append(f"{name}: {e}")

        lines = ["# Groceries Added to Inventory!", ""]
        lines.append(f"Added {len(added)} items:")
        lines.append("")
        for item in added:
            lines.append(f"- {item}")

        if errors:
            lines.append("")
            lines.append(f"## Errors ({len(errors)})")
            for err in errors:
                lines.append(f"- {err}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


# =============================================================================
# MEAL PLANNING
# =============================================================================

@router.get("/{token}/plan", response_class=PlainTextResponse)
async def add_to_plan(
    token: str,
    meal: str = Query(..., description="Meal name to search for"),
    slot: str = Query("dinner", description="Slot: breakfast/lunch/dinner/snack"),
    day: Optional[str] = Query(None, description="Date YYYY-MM-DD (default: today)"),
    scale: float = Query(1.0, description="Scale factor (1.0 = normal)"),
):
    """Add a meal to the plan."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()
    planned_date = day or date.today().isoformat()

    # Find meal
    result = (
        supabase.table("foodos2_food_items")
        .select("id, name, kind")
        .eq("user_id", user_id)
        .ilike("name", f"%{meal}%")
        .in_("kind", ["meal", "snack"])
        .limit(5)
        .execute()
    )

    if not result.data:
        # Try any food item
        result = (
            supabase.table("foodos2_food_items")
            .select("id, name, kind")
            .eq("user_id", user_id)
            .ilike("name", f"%{meal}%")
            .limit(5)
            .execute()
        )

    if not result.data:
        return f"Could not find '{meal}' in your food library.\n\nTip: Use /claude/{{token}}/recipes?q={meal} to search your recipes."

    # If multiple matches, list them
    if len(result.data) > 1:
        lines = [f"Found {len(result.data)} matches for '{meal}':", ""]
        for i, item in enumerate(result.data, 1):
            lines.append(f"{i}. {item['name']} ({item['kind']})")
        lines.append("")
        lines.append(f"Please be more specific, e.g., ?meal={result.data[0]['name'].replace(' ', '+')}")
        return "\n".join(lines)

    food_item = result.data[0]

    # Add to plan
    entry = {
        "user_id": user_id,
        "food_item_id": food_item["id"],
        "planned_date": planned_date,
        "slot": slot.lower(),
        "scale_factor": scale,
        "is_batch_prepped": False,
        "is_logged": False,
    }
    supabase.table("foodos2_plan_entries").insert(entry).execute()

    scale_str = f" (x{scale})" if scale != 1.0 else ""
    return f"Added {food_item['name']}{scale_str} to {slot} on {planned_date}"


# =============================================================================
# RECIPES - Search and view
# =============================================================================

@router.get("/{token}/recipes", response_class=PlainTextResponse)
async def search_recipes(
    token: str,
    q: str = Query("", description="Search query"),
    kind: Optional[str] = Query(None, description="Filter by kind: meal/snack/ingredient"),
):
    """Search recipes and food items."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()

    query = (
        supabase.table("foodos2_food_items")
        .select("name, kind, calories_per_100g, protein_g_per_100g, description")
        .eq("user_id", user_id)
        .limit(20)
    )

    if q:
        query = query.ilike("name", f"%{q}%")

    if kind:
        query = query.eq("kind", kind)
    else:
        query = query.in_("kind", ["meal", "snack"])

    result = query.execute()

    title = "# Recipes"
    if q:
        title += f" matching '{q}'"

    lines = [title, ""]

    if result.data:
        for item in result.data:
            name = item["name"]
            kind = item.get("kind", "")
            cal = item.get("calories_per_100g") or 0
            protein = item.get("protein_g_per_100g") or 0
            desc = item.get("description", "")

            line = f"- {name}"
            if cal or protein:
                line += f" ({cal:.0f} cal, {protein:.0f}g protein per 100g)"
            lines.append(line)

            if desc:
                lines.append(f"  {desc[:100]}...")
    else:
        lines.append("No recipes found.")
        if q:
            lines.append(f"\nTry a different search term or check /claude/{{token}}/recipes to see all.")

    return "\n".join(lines)


@router.get("/{token}/recipe", response_class=PlainTextResponse)
async def get_recipe(
    token: str,
    name: str = Query(..., description="Recipe name"),
    scale: float = Query(1.0, description="Scale factor"),
):
    """Get full recipe details including ingredients."""
    user = await get_user_from_token(token)
    user_id = user["user_id"]

    supabase = get_supabase()

    # Find recipe
    result = (
        supabase.table("foodos2_food_items")
        .select("id, name, kind, description, calories_per_100g, protein_g_per_100g, carbs_g_per_100g, fat_g_per_100g, prep_steps")
        .eq("user_id", user_id)
        .ilike("name", f"%{name}%")
        .limit(1)
        .execute()
    )

    if not result.data:
        return f"Could not find recipe '{name}'"

    recipe = result.data[0]
    recipe_id = recipe["id"]

    lines = [f"# {recipe['name']}", ""]

    if recipe.get("description"):
        lines.append(recipe["description"])
        lines.append("")

    # Nutrition per 100g
    lines.append("## Nutrition (per 100g)")
    lines.append(f"- Calories: {recipe.get('calories_per_100g', 0):.0f}")
    lines.append(f"- Protein: {recipe.get('protein_g_per_100g', 0):.1f}g")
    lines.append(f"- Carbs: {recipe.get('carbs_g_per_100g', 0):.1f}g")
    lines.append(f"- Fat: {recipe.get('fat_g_per_100g', 0):.1f}g")
    lines.append("")

    # Get ingredients from recipe graph
    edges = (
        supabase.table("foodos2_recipe_edges")
        .select("quantity_g, foodos2_food_items!foodos2_recipe_edges_child_id_fkey(name)")
        .eq("parent_id", recipe_id)
        .execute()
    )

    if edges.data:
        lines.append("## Ingredients")
        if scale != 1.0:
            lines.append(f"(scaled x{scale})")
        lines.append("")

        for edge in edges.data:
            child = edge.get("foodos2_food_items", {}) or {}
            child_name = child.get("name", "Unknown")
            qty = (edge.get("quantity_g", 0) or 0) * scale
            lines.append(f"- {child_name}: {format_quantity(qty)}")
        lines.append("")

    # Prep steps
    prep_steps = recipe.get("prep_steps", [])
    if prep_steps:
        lines.append("## Instructions")
        for i, step in enumerate(prep_steps, 1):
            lines.append(f"{i}. {step}")

    return "\n".join(lines)
