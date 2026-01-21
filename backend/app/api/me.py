"""
Simple text endpoints for Claude mobile/web access.

These endpoints return plain text summaries that Claude can easily read.
Only accessible from local network (192.168.x.x).

Endpoints:
  /me/xander/today     - Xander's daily summary
  /me/xander/inventory - Xander's inventory
  /me/xander/add       - Add to Xander's inventory
  /me/skiler/today     - Skiler's daily summary
  /me/skiler/inventory - Skiler's inventory
  /me/skiler/add       - Add to Skiler's inventory
"""

from datetime import date, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.supabase import get_supabase_client as get_supabase
from app.services.nutrition import get_nutrition_service

router = APIRouter(prefix="/me", tags=["me"])

# User mappings
USERS = {
    "xander": "b7ddfbbd-58c0-4076-9406-58dd1930aee5",
    "skiler": "5fc549ee-ce69-4539-b3d7-73b8637c21bc",
}


def check_local_network(request: Request):
    """Ensure request is from local network only."""
    client_ip = request.client.host if request.client else ""

    local_prefixes = ("192.168.", "10.", "172.16.", "172.17.", "172.18.",
                      "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                      "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                      "172.29.", "172.30.", "172.31.", "127.", "::1", "localhost")

    if not any(client_ip.startswith(prefix) for prefix in local_prefixes):
        raise HTTPException(status_code=403, detail="Local network access only")


def get_user_id(username: str) -> str:
    """Get user ID from username."""
    user_id = USERS.get(username.lower())
    if not user_id:
        raise HTTPException(status_code=404, detail=f"Unknown user: {username}")
    return user_id


# =============================================================================
# TODAY - Daily summary
# =============================================================================

@router.get("/{username}/today", response_class=PlainTextResponse)
async def today_summary(request: Request, username: str):
    """Get today's meal plan, nutrition, and expiring items."""
    check_local_network(request)
    user_id = get_user_id(username)

    supabase = get_supabase()
    today = date.today()
    today_str = today.isoformat()
    lines = [f"# {username.title()}'s Day ({today_str})", ""]

    # 1. Meal Plan
    result = (
        supabase.table("foodos2_plan_entries")
        .select("slot, scale_factor, foodos2_food_items(name, kind)")
        .eq("user_id", user_id)
        .eq("planned_date", today_str)
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
        svc = get_nutrition_service()
        stats = await svc.get_daily_stats(user_id, today, include_supplements=True, include_planned=True)

        lines.append("## Nutrition")
        lines.append(f"- Calories: {stats.nutrition.macros.calories:.0f} / {stats.target_calories:.0f} kcal")
        lines.append(f"- Protein: {stats.nutrition.macros.protein_g:.0f}g")
        lines.append(f"- Carbs: {stats.nutrition.macros.carbs_g:.0f}g")
        lines.append(f"- Fat: {stats.nutrition.macros.fat_g:.0f}g")

        if stats.vitamin_score is not None:
            lines.append(f"- Vitamins: {stats.vitamin_score:.0f}% | Minerals: {stats.mineral_score:.0f}%")
    except Exception as e:
        lines.append("## Nutrition")
        lines.append(f"- Error loading: {e}")
    lines.append("")

    # 3. Expiring Items
    result = (
        supabase.table("foodos2_inventory_items")
        .select("quantity_g, expiration_date, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .not_.is_("expiration_date", "null")
        .lte("expiration_date", (date.today() + timedelta(days=3)).isoformat())
        .order("expiration_date")
        .execute()
    )

    if result.data:
        lines.append("## Expiring Soon")
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

    return "\n".join(lines)


# =============================================================================
# INVENTORY - View inventory
# =============================================================================

@router.get("/{username}/inventory", response_class=PlainTextResponse)
async def inventory_summary(request: Request, username: str):
    """Get current inventory."""
    check_local_network(request)
    user_id = get_user_id(username)

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

    lines = [f"# {username.title()}'s Inventory ({len(result.data)} items)", ""]

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


# =============================================================================
# ADD - Add to inventory (GET for Claude mobile compatibility)
# =============================================================================

@router.get("/{username}/add", response_class=PlainTextResponse)
async def add_to_inventory(
    request: Request,
    username: str,
    item: str,
    qty: float,
    storage: str = "refrigerator",
    expires: str | None = None,
):
    """
    Add item to inventory.

    Args:
        item: Food item name (e.g., "ground beef", "eggs")
        qty: Quantity in grams (use 454 for 1 lb, 600 for dozen eggs)
        storage: refrigerator, freezer, or pantry
        expires: Expiration date YYYY-MM-DD (optional)

    Example: /me/xander/add?item=ground%20beef&qty=2724&storage=refrigerator
    """
    check_local_network(request)
    user_id = get_user_id(username)

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

    # Add to inventory
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

    # Format response
    qty_lbs = qty / 454
    exp_str = f", expires {expires}" if expires else ""

    return f"Added {qty:.0f}g ({qty_lbs:.1f} lbs) of {food_name} to {username}'s {storage}{exp_str}"


# =============================================================================
# USE - Subtract from inventory
# =============================================================================

@router.get("/{username}/use", response_class=PlainTextResponse)
async def use_from_inventory(
    request: Request,
    username: str,
    item: str,
    qty: float,
):
    """
    Subtract quantity from inventory item.

    Args:
        item: Food item name
        qty: Quantity in grams to subtract

    Example: /me/xander/use?item=ground%20beef&qty=454
    """
    check_local_network(request)
    user_id = get_user_id(username)

    supabase = get_supabase()

    # Find inventory item
    result = (
        supabase.table("foodos2_inventory_items")
        .select("id, quantity_g, foodos2_food_items(name)")
        .eq("user_id", user_id)
        .execute()
    )

    matching = None
    for inv_item in result.data:
        food = inv_item.get("foodos2_food_items", {})
        name = food.get("name", "") if food else ""
        if item.lower() in name.lower():
            matching = inv_item
            break

    if not matching:
        return f"Could not find '{item}' in {username}'s inventory"

    old_qty = float(matching["quantity_g"])
    new_qty = max(0, old_qty - qty)

    supabase.table("foodos2_inventory_items").update(
        {"quantity_g": new_qty}
    ).eq("id", matching["id"]).execute()

    food_name = matching.get("foodos2_food_items", {}).get("name", item)
    return f"Used {qty:.0f}g of {food_name}. Remaining: {new_qty:.0f}g"


# =============================================================================
# PLAN - Add meal to plan
# =============================================================================

@router.get("/{username}/plan", response_class=PlainTextResponse)
async def add_to_plan(
    request: Request,
    username: str,
    meal: str,
    slot: str = "dinner",
    day: str | None = None,
):
    """
    Add meal to plan.

    Args:
        meal: Meal name to search for
        slot: breakfast, lunch, dinner, or snack
        day: Date YYYY-MM-DD (defaults to today)

    Example: /me/xander/plan?meal=chicken%20pasta&slot=dinner
    """
    check_local_network(request)
    user_id = get_user_id(username)

    supabase = get_supabase()
    planned_date = day or date.today().isoformat()

    # Find meal
    result = (
        supabase.table("foodos2_food_items")
        .select("id, name, kind")
        .eq("user_id", user_id)
        .ilike("name", f"%{meal}%")
        .in_("kind", ["meal", "snack"])
        .limit(1)
        .execute()
    )

    if not result.data:
        # Try any food item
        result = (
            supabase.table("foodos2_food_items")
            .select("id, name, kind")
            .eq("user_id", user_id)
            .ilike("name", f"%{meal}%")
            .limit(1)
            .execute()
        )

    if not result.data:
        return f"Could not find '{meal}' in {username}'s food library"

    food_item = result.data[0]

    # Add to plan
    entry = {
        "user_id": user_id,
        "food_item_id": food_item["id"],
        "planned_date": planned_date,
        "slot": slot.lower(),
        "scale_factor": 1.0,
        "is_batch_prepped": False,
        "is_logged": False,
    }
    supabase.table("foodos2_plan_entries").insert(entry).execute()

    return f"Added {food_item['name']} to {username}'s {slot} on {planned_date}"


# =============================================================================
# GROCERY - Get grocery list
# =============================================================================

@router.get("/{username}/grocery", response_class=PlainTextResponse)
async def get_grocery_list(
    request: Request,
    username: str,
    days: int = 7,
):
    """
    Get grocery list for upcoming days.

    Args:
        days: Number of days to plan for (default 7)

    Example: /me/xander/grocery?days=7
    """
    check_local_network(request)
    user_id = get_user_id(username)

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

        lines = [f"# {username.title()}'s Grocery List", ""]
        lines.append(f"{today.isoformat()} to {end.isoformat()} ({days} days)")
        lines.append(f"{grocery_list.items_to_buy_count} items needed")
        lines.append("")

        if not grocery_list.items:
            lines.append("Nothing to buy!")
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
                        # Convert to friendly units
                        if to_buy >= 454:
                            amt = f"{to_buy/454:.1f} lbs"
                        else:
                            amt = f"{to_buy:.0f}g"
                        lines.append(f"- [ ] {name}: {amt}")
                lines.append("")
        else:
            # Flat list
            for item in grocery_list.items:
                if item.to_buy_g > 0:
                    name = item.name
                    to_buy = item.to_buy_g
                    if to_buy >= 454:
                        amt = f"{to_buy/454:.1f} lbs"
                    else:
                        amt = f"{to_buy:.0f}g"
                    lines.append(f"- [ ] {name}: {amt}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating grocery list: {e}"


# =============================================================================
# BOUGHT - Add grocery list to inventory (done shopping!)
# =============================================================================

@router.get("/{username}/bought", response_class=PlainTextResponse)
async def mark_groceries_bought(
    request: Request,
    username: str,
    days: int = 7,
    storage: str = "refrigerator",
):
    """
    Add all items from grocery list to inventory.
    Call this after shopping to update inventory with everything you bought.

    Args:
        days: Days the grocery list was for (default 7)
        storage: Default storage location (refrigerator, freezer, pantry)

    Example: /me/xander/bought?days=7&storage=refrigerator
    """
    check_local_network(request)
    user_id = get_user_id(username)

    from app.models.grocery import GroceryGenerationRequest
    from app.services.grocery import generate_grocery_list

    supabase = get_supabase()
    today = date.today()
    end = today + timedelta(days=days - 1)

    try:
        # Generate the grocery list
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
            item_storage = storage
            cat = str(item.category.value) if item.category else ""
            if "frozen" in cat.lower():
                item_storage = "freezer"
            elif "pantry" in cat.lower() or "dry" in cat.lower():
                item_storage = "pantry"
            elif "produce" in cat.lower() or "meat" in cat.lower() or "dairy" in cat.lower():
                item_storage = "refrigerator"

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
                        # Create new ingredient
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

                # Check if already in inventory - if so, add to it
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
                    supabase.table("foodos2_inventory_items").update(
                        {"quantity_g": new_qty}
                    ).eq("id", existing.data[0]["id"]).execute()
                else:
                    # Add new
                    inventory_item = {
                        "user_id": user_id,
                        "food_item_id": food_item_id,
                        "quantity_g": qty,
                        "date_added": today.isoformat(),
                        "storage_type": item_storage,
                    }
                    supabase.table("foodos2_inventory_items").insert(inventory_item).execute()

                added.append(f"{name}: {qty:.0f}g")

            except Exception as e:
                errors.append(f"{name}: {e}")

        lines = [f"# Added to {username.title()}'s Inventory", ""]
        lines.append(f"Added {len(added)} items from grocery list:")
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
        return f"Error processing grocery list: {e}"


# =============================================================================
# SEARCH - Search recipes
# =============================================================================

@router.get("/{username}/recipes", response_class=PlainTextResponse)
async def search_recipes(request: Request, username: str, q: str = ""):
    """Search recipes or list recent ones."""
    check_local_network(request)
    user_id = get_user_id(username)

    supabase = get_supabase()

    query = (
        supabase.table("foodos2_food_items")
        .select("name, kind, calories_per_100g, protein_g_per_100g")
        .eq("user_id", user_id)
        .in_("kind", ["meal", "snack"])
        .limit(20)
    )

    if q:
        query = query.ilike("name", f"%{q}%")

    result = query.execute()

    title = f"# {username.title()}'s Recipes"
    if q:
        title += f" matching '{q}'"
    lines = [title, ""]

    if result.data:
        for item in result.data:
            name = item["name"]
            cal = item.get("calories_per_100g") or 0
            protein = item.get("protein_g_per_100g") or 0
            lines.append(f"- {name} ({cal:.0f} cal, {protein:.0f}g protein)")
    else:
        lines.append("No recipes found")

    return "\n".join(lines)
