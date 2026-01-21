"""MCP Server for Slop Food App.

Exposes food app functionality to Claude Code and Claude Chat
via the Model Context Protocol (MCP).
"""

from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

from .client import pi_client
from .config import config

# Initialize FastMCP server with description
mcp = FastMCP(
    "slop",
    instructions="""You are a helpful food and nutrition assistant connected to the user's personal food app (Slop).

You have access to their:
- **Meal Plans**: What they're planning to eat each day (breakfast, lunch, dinner, snacks)
- **Nutrition Data**: Detailed macro and micronutrient tracking with RDA percentages
- **Inventory**: What food they have on hand with expiration dates
- **Recipe Library**: Their saved recipes with ingredients and nutrition
- **Grocery Lists**: Auto-generated shopping lists based on meal plans

Key behaviors:
1. **Be proactive**: If asked about dinner, also mention if anything is expiring that could be used
2. **Be specific**: Use actual data from their library, not generic advice
3. **Track nutrition**: When discussing meals, mention protein and calorie impact
4. **Respect inventory**: When suggesting meals, consider what they have on hand
5. **Be conversational**: "You've got chicken expiring tomorrow - how about that stir fry recipe?"

Common user intents:
- "What's for dinner?" → Check meal plan, show recipe if planned
- "How am I doing on protein?" → Check daily nutrition
- "What do I need to buy?" → Generate grocery list
- "I just went shopping" → Help update inventory
- "Make me a recipe for X" → Use AI recipe generation
- "What should I make with [ingredient]?" → Search recipes + check inventory

Always use the actual tools to get real data rather than making assumptions.""",
)


# ============================================================================
# PROMPTS - Templates to guide AI responses
# ============================================================================


@mcp.prompt()
def daily_summary() -> str:
    """Get a complete daily food summary - what's planned, nutrition status, and inventory alerts."""
    return """Please provide a comprehensive daily food summary by:

1. First, call `get_meal_plan` for today to see what meals are planned
2. Then call `get_daily_nutrition` to see nutrition stats (calories, macros, micronutrients)
3. Finally call `get_inventory` to check for any expiring items

Summarize the results in a friendly format:
- What's for breakfast, lunch, dinner, snacks today
- How nutrition is tracking vs targets (calories, protein especially)
- Any items expiring soon that should be used
- Suggestions if nutrition is off-target or items need to be used up"""


@mcp.prompt()
def weekly_meal_prep() -> str:
    """Plan meals for the week and generate a shopping list."""
    return """Help plan meals for the upcoming week:

1. Call `get_meal_plan` with days=7 to see what's already planned
2. If meals are missing, suggest using `generate_meal_plan` or `add_meal_to_plan`
3. Call `get_grocery_list` with days=7 to generate the shopping list
4. Call `get_inventory` to see what's already on hand

Present:
- The week's meal plan organized by day
- A consolidated grocery list (items already in inventory are subtracted)
- Any suggestions for variety or nutrition balance"""


@mcp.prompt()
def whats_for_dinner() -> str:
    """Quick answer about what's planned for dinner tonight."""
    return """The user wants to know what's for dinner.

1. Call `get_meal_plan` for today
2. Look for the dinner slot
3. If a meal is planned, optionally call `get_recipe_details` to show ingredients
4. If no dinner is planned, suggest meals from their library using `search_food_items`

Keep the response concise and helpful."""


@mcp.prompt()
def nutrition_check() -> str:
    """Check how nutrition is tracking for the day."""
    return """Check nutrition progress for today:

1. Call `get_daily_nutrition` with today's date
2. Analyze:
   - Calories consumed vs target
   - Protein intake (aim for target)
   - Key micronutrients and any deficiencies
   - Vitamin and mineral scores

Provide actionable feedback:
- If under calories/protein, suggest adding a snack or larger portions
- If low on specific nutrients, suggest foods rich in those
- Celebrate if on track!"""


@mcp.prompt()
def use_expiring_ingredients() -> str:
    """Find recipes that use ingredients expiring soon."""
    return """Help use up expiring ingredients:

1. Call `get_inventory` with include_expired=True to see what's expiring
2. For items expiring within 3 days, use `search_food_items` to find recipes using them
3. Suggest meals that incorporate expiring ingredients
4. Optionally use `add_meal_to_plan` to schedule suggested meals

Prioritize:
- Items expiring soonest
- Combining multiple expiring items in one meal
- Practical meal suggestions for the current meal slot"""


@mcp.prompt()
def create_recipe_from_idea() -> str:
    """Generate a new recipe from a description."""
    return """Help create a new recipe:

1. Use `generate_recipe` with the user's description
   - mode="lazy" for quick/simple recipes
   - mode="healthy" if they want nutritious options
   - mode="fancy" for gourmet dishes

2. Present the generated recipe with:
   - Ingredients list with amounts
   - Step-by-step instructions
   - Estimated nutrition info
   - Prep and cook times

3. Ask if they want to:
   - Modify anything (use AI to adjust)
   - Add it to their meal plan
   - Save it to their recipe library"""


@mcp.prompt()
def inventory_after_shopping() -> str:
    """Update inventory after a grocery shopping trip."""
    return """Help update inventory after shopping:

For each item the user mentions they bought:
1. Use `add_to_inventory` with:
   - food_item_name: the item name
   - quantity_g: amount in grams (convert from units if needed)
   - expiration_date: estimate based on food type if not provided
   - storage_type: pantry, refrigerator, or freezer

Common conversions:
- 1 lb = 454g
- 1 dozen eggs ≈ 600g
- 1 gallon milk = 3785g
- 1 chicken breast ≈ 170g

Confirm each addition and summarize at the end."""


@mcp.prompt()
def log_meal_consumption() -> str:
    """Record that a meal was eaten and update inventory."""
    return """When the user says they ate something:

1. If it was a planned meal, note it's been consumed
2. If ingredients were used from inventory, call `update_inventory_quantity` with negative quantity_change_g to subtract what was used
3. Confirm the update

Example: "I made the chicken stir fry"
- Look up the recipe ingredients
- Subtract each ingredient amount from inventory
- Confirm consumption logged"""


@mcp.prompt()
def find_high_protein_meals() -> str:
    """Search for high-protein meal options."""
    return """Find high-protein meals:

1. Call `search_food_items` with query terms like "chicken", "beef", "fish", "protein"
2. Filter results for meals (kind="meal")
3. Present options sorted by protein content
4. Show protein per serving for each option

The user likely wants to hit protein goals, so prioritize:
- Meals with 30g+ protein
- Lean protein sources
- Variety of protein types"""


@mcp.prompt()
def quick_nutrition_lookup() -> str:
    """Look up nutrition for any food item."""
    return """To look up nutrition for a food:

1. First try `search_food_items` to check if it's in the user's library
2. If not found, try `search_usda` for USDA database lookup
3. If still not found, use `lookup_nutrition` for AI-powered estimation

Present nutrition per 100g:
- Calories
- Protein, carbs, fat
- Notable micronutrients

Offer to add it to their food library if useful."""


# ============================================================================
# MEAL PLANNING TOOLS
# ============================================================================


@mcp.tool()
async def get_meal_plan(
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 1,
    user_id: str | None = None,
) -> str:
    """Get planned meals for a date or date range.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, use days instead)
        days: Number of days to fetch (default 1, ignored if end_date provided)
        user_id: User ID (uses default if not provided)

    Returns:
        Formatted meal plan with meals organized by date and slot
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    start = start_date or date.today().isoformat()
    if end_date:
        end = end_date
    else:
        start_dt = date.fromisoformat(start)
        end = (start_dt + timedelta(days=days - 1)).isoformat()

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        result = (
            supabase.table("foodos2_plan_entries")
            .select("*, foodos2_food_items(name, kind)")
            .eq("user_id", uid)
            .gte("planned_date", start)
            .lte("planned_date", end)
            .order("planned_date")
            .order("slot")
            .execute()
        )

        entries = result.data
        if not entries:
            return f"No meals planned for {start}" + (f" to {end}" if start != end else "")

        by_date: dict[str, dict[str, list]] = {}
        for entry in entries:
            d = entry["planned_date"]
            slot = entry["slot"]
            food = entry.get("foodos2_food_items", {})
            name = food.get("name", "Unknown") if food else "Unknown"
            kind = food.get("kind", "") if food else ""
            scale = entry.get("scale_factor", 1.0)

            if d not in by_date:
                by_date[d] = {}
            if slot not in by_date[d]:
                by_date[d][slot] = []

            meal_str = name
            if scale and scale != 1.0:
                meal_str += f" (x{scale})"
            if kind:
                meal_str += f" [{kind}]"
            by_date[d][slot].append(meal_str)

        lines = ["# Meal Plan", ""]
        slot_order = ["breakfast", "lunch", "dinner", "snack"]

        for d in sorted(by_date.keys()):
            lines.append(f"## {d}")
            for slot in slot_order:
                if slot in by_date[d]:
                    meals = by_date[d][slot]
                    lines.append(f"**{slot.title()}**: {', '.join(meals)}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching meal plan: {e}"


@mcp.tool()
async def get_daily_nutrition(
    target_date: str | None = None,
    include_supplements: bool = True,
    include_planned: bool = True,
    user_id: str | None = None,
) -> str:
    """Get comprehensive nutrition stats for a day including macros and micronutrients.

    Args:
        target_date: Date in YYYY-MM-DD format (defaults to today)
        include_supplements: Include supplements in nutrition calculation
        include_planned: Include planned but not yet consumed meals
        user_id: User ID (uses default if not provided)

    Returns:
        Formatted nutrition summary with calories, macros, and top micronutrients
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    target = target_date or date.today().isoformat()

    try:
        data = await pi_client.get_daily_nutrition(uid, target, include_supplements, include_planned)

        lines = [f"# Nutrition for {data.get('date', target)}", ""]

        nutrition = data.get("nutrition", {})
        target_cal = data.get("target_calories", 0)
        actual_cal = nutrition.get("calories", 0)
        variance = data.get("calories_variance", 0)

        lines.append("## Calories")
        lines.append(f"- **Consumed**: {actual_cal:.0f} kcal")
        if target_cal:
            lines.append(f"- **Target**: {target_cal:.0f} kcal")
            lines.append(f"- **Variance**: {variance:+.0f} kcal")
        lines.append("")

        lines.append("## Macros")
        lines.append(f"- **Protein**: {nutrition.get('protein_g', 0):.1f}g")
        lines.append(f"- **Carbs**: {nutrition.get('carbs_g', 0):.1f}g")
        lines.append(f"- **Fat**: {nutrition.get('fat_g', 0):.1f}g")
        if nutrition.get("fiber_g"):
            lines.append(f"- **Fiber**: {nutrition.get('fiber_g', 0):.1f}g")
        lines.append("")

        vitamin_score = data.get("vitamin_score")
        mineral_score = data.get("mineral_score")
        overall_score = data.get("overall_nutrition_score")

        if any([vitamin_score, mineral_score, overall_score]):
            lines.append("## Nutrition Scores")
            if vitamin_score is not None:
                lines.append(f"- **Vitamins**: {vitamin_score:.0f}%")
            if mineral_score is not None:
                lines.append(f"- **Minerals**: {mineral_score:.0f}%")
            if overall_score is not None:
                lines.append(f"- **Overall**: {overall_score:.0f}%")
            lines.append("")

        top_micros = nutrition.get("top_micronutrients", [])
        if top_micros:
            lines.append("## Top Micronutrients")
            for micro in top_micros[:8]:
                name = micro.get("name", "Unknown")
                pct = micro.get("percent_rda", 0)
                amount = micro.get("amount", 0)
                unit = micro.get("unit", "")
                lines.append(f"- **{name}**: {amount:.1f}{unit} ({pct:.0f}% RDA)")
            lines.append("")

        lines.append(f"*Meals logged: {data.get('meals_logged', 0)}*")
        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching nutrition: {e}"


@mcp.tool()
async def add_meal_to_plan(
    food_item_name: str,
    planned_date: str,
    slot: str = "dinner",
    scale_factor: float = 1.0,
    user_id: str | None = None,
) -> str:
    """Add a meal or food item to the meal plan.

    Args:
        food_item_name: Name of the food item (will search for it)
        planned_date: Date in YYYY-MM-DD format
        slot: Meal slot: "breakfast", "lunch", "dinner", or "snack"
        scale_factor: Portion scale (1.0 = normal, 0.5 = half, 2.0 = double)
        user_id: User ID (uses default if not provided)

    Returns:
        Confirmation message with the added meal
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    if slot not in ["breakfast", "lunch", "dinner", "snack"]:
        return f"Error: Invalid slot '{slot}'. Use: breakfast, lunch, dinner, or snack"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        result = (
            supabase.table("foodos2_food_items")
            .select("id, name, kind")
            .eq("user_id", uid)
            .ilike("name", f"%{food_item_name}%")
            .limit(5)
            .execute()
        )

        if not result.data:
            return f"Could not find food item matching '{food_item_name}'"

        food_item = None
        for item in result.data:
            if item["name"].lower() == food_item_name.lower():
                food_item = item
                break
        if not food_item:
            for item in result.data:
                if item.get("kind") == "meal":
                    food_item = item
                    break
        if not food_item:
            food_item = result.data[0]

        entry = {
            "user_id": uid,
            "food_item_id": food_item["id"],
            "planned_date": planned_date,
            "slot": slot,
            "scale_factor": scale_factor,
            "is_batch_prepped": False,
            "is_logged": False,
        }

        supabase.table("foodos2_plan_entries").insert(entry).execute()

        scale_str = f" (x{scale_factor})" if scale_factor != 1.0 else ""
        return f"Added **{food_item['name']}**{scale_str} to {slot} on {planned_date}"

    except Exception as e:
        return f"Error adding meal to plan: {e}"


@mcp.tool()
async def remove_meal_from_plan(
    food_item_name: str,
    planned_date: str,
    slot: str | None = None,
    user_id: str | None = None,
) -> str:
    """Remove a meal from the plan.

    Args:
        food_item_name: Name of the food item to remove
        planned_date: Date in YYYY-MM-DD format
        slot: Specific slot to remove from (optional, removes from any if not specified)
        user_id: User ID (uses default if not provided)

    Returns:
        Confirmation message
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        query = (
            supabase.table("foodos2_plan_entries")
            .select("id, slot, foodos2_food_items(name)")
            .eq("user_id", uid)
            .eq("planned_date", planned_date)
        )

        if slot:
            query = query.eq("slot", slot)

        result = query.execute()

        if not result.data:
            return f"No meals found on {planned_date}" + (f" for {slot}" if slot else "")

        matching = None
        for entry in result.data:
            food = entry.get("foodos2_food_items", {})
            name = food.get("name", "") if food else ""
            if food_item_name.lower() in name.lower():
                matching = entry
                break

        if not matching:
            return f"Could not find '{food_item_name}' on {planned_date}"

        supabase.table("foodos2_plan_entries").delete().eq("id", matching["id"]).execute()

        food_name = matching.get("foodos2_food_items", {}).get("name", food_item_name)
        return f"Removed **{food_name}** from {matching['slot']} on {planned_date}"

    except Exception as e:
        return f"Error removing meal from plan: {e}"


@mcp.tool()
async def generate_meal_plan(
    start_date: str,
    days: int = 7,
    daily_calories: int = 2000,
    user_id: str | None = None,
) -> str:
    """Generate a meal plan using AI based on your food library.

    Args:
        start_date: Start date in YYYY-MM-DD format
        days: Number of days to plan (1-14, default 7)
        daily_calories: Target daily calories (default 2000)
        user_id: User ID (uses default if not provided)

    Returns:
        Generated meal plan summary
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    days = min(max(days, 1), 14)

    try:
        data = await pi_client.post(
            "/api/planning/save",
            json={
                "user_id": uid,
                "start_date": start_date,
                "days": days,
                "daily_calories": daily_calories,
                "protein_pct": 30,
                "carbs_pct": 40,
                "fat_pct": 30,
                "breakfasts_per_day": 1,
                "lunches_per_day": 1,
                "dinners_per_day": 1,
                "snacks_per_day": 1,
                "prefer_variety": True,
                "match_macros": True,
            },
        )

        if data.get("success"):
            entries = data.get("entries_created", 0)
            avg_cal = data.get("avg_daily_calories", 0)
            accuracy = data.get("calorie_accuracy_pct", 0)

            return "\n".join([
                "# Meal Plan Generated",
                "",
                f"**{entries} meals** planned from {start_date} for {days} days",
                "",
                f"- Target: {daily_calories} cal/day",
                f"- Actual avg: {avg_cal:.0f} cal/day",
                f"- Accuracy: {accuracy:.0f}%",
                "",
                "Use `get_meal_plan` to see the full plan.",
            ])
        else:
            return f"Failed to generate plan: {data}"

    except Exception as e:
        return f"Error generating meal plan: {e}"


# ============================================================================
# GROCERY & INVENTORY TOOLS
# ============================================================================


@mcp.tool()
async def get_grocery_list(
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 7,
    subtract_inventory: bool = True,
    user_id: str | None = None,
) -> str:
    """Generate a grocery list for a date range based on meal plans.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to today)
        end_date: End date in YYYY-MM-DD format (optional)
        days: Number of days to include (default 7, ignored if end_date provided)
        subtract_inventory: Whether to subtract items already in inventory
        user_id: User ID (uses default if not provided)

    Returns:
        Formatted grocery list organized by category
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    start = start_date or date.today().isoformat()
    if end_date:
        end = end_date
    else:
        start_dt = date.fromisoformat(start)
        end = (start_dt + timedelta(days=days - 1)).isoformat()

    try:
        data = await pi_client.get_grocery_list(uid, start, end, subtract_inventory=subtract_inventory)

        lines = ["# Grocery List", ""]
        lines.append(f"*{start} to {end}*")
        lines.append("")

        items_count = data.get("items_count", 0)
        meals_included = data.get("meals_included", 0)
        estimated_price = data.get("estimated_total_price")

        lines.append(f"**{items_count} items** for {meals_included} meals")
        if estimated_price:
            lines.append(f"Estimated total: ${estimated_price:.2f}")
        lines.append("")

        by_category = data.get("by_category", {})
        if by_category:
            for category, items in sorted(by_category.items()):
                lines.append(f"## {category}")
                for item in items:
                    name = item.get("name", "Unknown")
                    to_buy = item.get("to_buy_g", 0)
                    display_amount = item.get("display_amount")
                    display_unit = item.get("display_unit", "g")

                    if display_amount:
                        amount_str = f"{display_amount} {display_unit}"
                    else:
                        amount_str = f"{to_buy:.0f}g"

                    price = item.get("estimated_price")
                    price_str = f" (~${price:.2f})" if price else ""

                    lines.append(f"- [ ] {name}: {amount_str}{price_str}")
                lines.append("")
        else:
            items = data.get("items", [])
            for item in items:
                name = item.get("name", "Unknown")
                to_buy = item.get("to_buy_g", 0)
                lines.append(f"- [ ] {name}: {to_buy:.0f}g")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating grocery list: {e}"


@mcp.tool()
async def get_inventory(
    include_expired: bool = False,
    user_id: str | None = None,
) -> str:
    """Get current inventory with quantities and expiration dates.

    Args:
        include_expired: Include items that have already expired
        user_id: User ID (uses default if not provided)

    Returns:
        Formatted inventory list with quantities and expiration info
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    try:
        items = await pi_client.get_inventory(uid, include_no_expiration=True)

        if not items:
            return "Inventory is empty"

        today = date.today()
        lines = ["# Inventory", ""]

        expired = []
        expiring_soon = []
        ok = []
        no_expiration = []

        for item in items:
            exp_date = item.get("expiration_date") or item.get("expires_at")
            if exp_date:
                exp = date.fromisoformat(exp_date) if isinstance(exp_date, str) else exp_date
                days_until = (exp - today).days
                if days_until < 0:
                    expired.append((item, days_until))
                elif days_until <= 7:
                    expiring_soon.append((item, days_until))
                else:
                    ok.append((item, days_until))
            else:
                no_expiration.append(item)

        def format_item(item, days=None):
            name = item.get("food_item_name") or item.get("name", "Unknown")
            qty = item.get("quantity_g", 0)
            unit_qty = item.get("quantity_units")
            unit_label = item.get("unit_label")

            if unit_qty and unit_label:
                qty_str = f"{unit_qty} {unit_label} ({qty:.0f}g)"
            else:
                qty_str = f"{qty:.0f}g"

            if days is not None:
                if days < 0:
                    exp_str = f" ⚠️ EXPIRED {abs(days)}d ago"
                elif days == 0:
                    exp_str = " ⚠️ EXPIRES TODAY"
                elif days <= 3:
                    exp_str = f" ⚠️ expires in {days}d"
                else:
                    exp_str = f" (expires in {days}d)"
            else:
                exp_str = ""

            return f"- {name}: {qty_str}{exp_str}"

        if expired and include_expired:
            lines.append("## ⚠️ Expired")
            for item, days in sorted(expired, key=lambda x: x[1]):
                lines.append(format_item(item, days))
            lines.append("")

        if expiring_soon:
            lines.append("## ⏰ Expiring Soon")
            for item, days in sorted(expiring_soon, key=lambda x: x[1]):
                lines.append(format_item(item, days))
            lines.append("")

        if ok:
            lines.append("## ✓ Good")
            for item, days in sorted(ok, key=lambda x: -x[1]):
                lines.append(format_item(item, days))
            lines.append("")

        if no_expiration:
            lines.append("## No Expiration Set")
            for item in no_expiration:
                lines.append(format_item(item))
            lines.append("")

        total = len(items)
        lines.append(f"*{total} items in inventory*")
        if expired and not include_expired:
            lines.append(f"*({len(expired)} expired items hidden)*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching inventory: {e}"


@mcp.tool()
async def add_to_inventory(
    food_item_name: str,
    quantity_g: float,
    expiration_date: str | None = None,
    storage_type: str = "refrigerator",
    user_id: str | None = None,
) -> str:
    """Add an item to inventory.

    Args:
        food_item_name: Name of the food item to add
        quantity_g: Quantity in grams
        expiration_date: Expiration date in YYYY-MM-DD format (optional)
        storage_type: Where stored: "pantry", "refrigerator", or "freezer"
        user_id: User ID (uses default if not provided)

    Returns:
        Confirmation message
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        result = (
            supabase.table("foodos2_food_items")
            .select("id, name")
            .eq("user_id", uid)
            .ilike("name", food_item_name)
            .limit(1)
            .execute()
        )

        if result.data:
            food_item_id = result.data[0]["id"]
            food_name = result.data[0]["name"]
        else:
            new_item = {
                "user_id": uid,
                "name": food_item_name,
                "kind": "ingredient",
                "serving_g": 100,
                "calories": 0,
                "protein_g": 0,
                "carbs_g": 0,
                "fat_g": 0,
            }
            result = supabase.table("foodos2_food_items").insert(new_item).execute()
            food_item_id = result.data[0]["id"]
            food_name = food_item_name

        inventory_item = {
            "user_id": uid,
            "food_item_id": food_item_id,
            "quantity_g": quantity_g,
            "date_added": date.today().isoformat(),
            "storage_type": storage_type,
        }
        if expiration_date:
            inventory_item["expiration_date"] = expiration_date

        supabase.table("foodos2_inventory_items").insert(inventory_item).execute()

        exp_str = f", expires {expiration_date}" if expiration_date else ""
        return f"Added {quantity_g:.0f}g of {food_name} to inventory ({storage_type}{exp_str})"

    except Exception as e:
        return f"Error adding to inventory: {e}"


@mcp.tool()
async def update_inventory_quantity(
    food_item_name: str,
    new_quantity_g: float | None = None,
    quantity_change_g: float | None = None,
    user_id: str | None = None,
) -> str:
    """Update quantity of an existing inventory item.

    Provide either new_quantity_g (absolute) or quantity_change_g (relative).

    Args:
        food_item_name: Name of the food item to update
        new_quantity_g: New absolute quantity in grams
        quantity_change_g: Amount to add (positive) or subtract (negative)
        user_id: User ID (uses default if not provided)

    Returns:
        Confirmation message with old and new quantities
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    if new_quantity_g is None and quantity_change_g is None:
        return "Error: Provide either new_quantity_g or quantity_change_g"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        result = (
            supabase.table("foodos2_inventory_items")
            .select("id, quantity_g, foodos2_food_items(name)")
            .eq("user_id", uid)
            .execute()
        )

        matching = None
        for item in result.data:
            food = item.get("foodos2_food_items", {})
            name = food.get("name", "") if food else ""
            if name.lower() == food_item_name.lower():
                matching = item
                break

        if not matching:
            for item in result.data:
                food = item.get("foodos2_food_items", {})
                name = food.get("name", "") if food else ""
                if food_item_name.lower() in name.lower():
                    matching = item
                    break

        if not matching:
            return f"Could not find '{food_item_name}' in inventory"

        old_qty = matching["quantity_g"]
        if new_quantity_g is not None:
            new_qty = new_quantity_g
        else:
            new_qty = old_qty + quantity_change_g

        if new_qty < 0:
            new_qty = 0

        supabase.table("foodos2_inventory_items").update({"quantity_g": new_qty}).eq(
            "id", matching["id"]
        ).execute()

        food_name = matching.get("foodos2_food_items", {}).get("name", food_item_name)
        change_str = (
            f"{old_qty:.0f}g → {new_qty:.0f}g"
            if new_quantity_g is not None
            else f"{old_qty:.0f}g {quantity_change_g:+.0f}g = {new_qty:.0f}g"
        )
        return f"Updated {food_name}: {change_str}"

    except Exception as e:
        return f"Error updating inventory: {e}"


@mcp.tool()
async def remove_from_inventory(
    food_item_name: str,
    user_id: str | None = None,
) -> str:
    """Remove an item from inventory completely.

    Args:
        food_item_name: Name of the food item to remove
        user_id: User ID (uses default if not provided)

    Returns:
        Confirmation message
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        result = (
            supabase.table("foodos2_inventory_items")
            .select("id, foodos2_food_items(name)")
            .eq("user_id", uid)
            .execute()
        )

        matching = None
        for item in result.data:
            food = item.get("foodos2_food_items", {})
            name = food.get("name", "") if food else ""
            if name.lower() == food_item_name.lower():
                matching = item
                break

        if not matching:
            for item in result.data:
                food = item.get("foodos2_food_items", {})
                name = food.get("name", "") if food else ""
                if food_item_name.lower() in name.lower():
                    matching = item
                    break

        if not matching:
            return f"Could not find '{food_item_name}' in inventory"

        supabase.table("foodos2_inventory_items").delete().eq("id", matching["id"]).execute()

        food_name = matching.get("foodos2_food_items", {}).get("name", food_item_name)
        return f"Removed {food_name} from inventory"

    except Exception as e:
        return f"Error removing from inventory: {e}"


# ============================================================================
# FOOD SEARCH TOOLS
# ============================================================================


@mcp.tool()
async def search_food_items(
    query: str,
    kind: str | None = None,
    limit: int = 20,
    user_id: str | None = None,
) -> str:
    """Search food items including ingredients, recipes, and products.

    Args:
        query: Search query (searches name and description)
        kind: Filter by kind: "ingredient", "meal", "snack", "product" (optional)
        limit: Maximum results to return (default 20, max 50)
        user_id: User ID (uses default if not provided)

    Returns:
        List of matching food items with nutrition info
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    try:
        from supabase import create_client

        supabase = create_client(config.supabase_url, config.supabase_key)

        q = (
            supabase.table("foodos2_food_items")
            .select("id, name, kind, calories_per_100g, protein_g_per_100g, carbs_g_per_100g, fat_g_per_100g")
            .eq("user_id", uid)
            .ilike("name", f"%{query}%")
            .limit(min(limit, 50))
        )

        if kind:
            q = q.eq("kind", kind)

        result = q.execute()
        items = result.data

        if not items:
            return f"No food items found matching '{query}'"

        lines = [f"# Search Results for '{query}'", ""]
        lines.append(f"Found {len(items)} items:")
        lines.append("")

        by_kind: dict[str, list] = {}
        for item in items:
            k = item.get("kind", "other")
            if k not in by_kind:
                by_kind[k] = []
            by_kind[k].append(item)

        kind_order = ["meal", "snack", "ingredient", "product", "other"]
        for k in kind_order:
            if k not in by_kind:
                continue
            lines.append(f"## {k.title()}s")
            for item in by_kind[k]:
                name = item["name"]
                cal = item.get("calories_per_100g") or 0
                protein = item.get("protein_g_per_100g") or 0
                item_id = item["id"]
                lines.append(f"- **{name}** (per 100g)")
                lines.append(f"  {cal:.0f} cal, {protein:.1f}g protein")
                lines.append(f"  ID: `{item_id}`")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching food items: {e}"


@mcp.tool()
async def get_recipe_details(
    recipe_id: str | None = None,
    recipe_name: str | None = None,
    scale: float = 1.0,
    user_id: str | None = None,
) -> str:
    """Get full recipe details including ingredients and nutrition.

    Provide either recipe_id or recipe_name.

    Args:
        recipe_id: UUID of the recipe
        recipe_name: Name of the recipe (will search for it)
        scale: Scale factor for the recipe (default 1.0)
        user_id: User ID (uses default if not provided)

    Returns:
        Full recipe with ingredients list and nutrition breakdown
    """
    uid = user_id or config.default_user_id
    if not uid:
        return "Error: No user_id provided and no default configured"

    if not recipe_id and not recipe_name:
        return "Error: Provide either recipe_id or recipe_name"

    try:
        if recipe_name and not recipe_id:
            from supabase import create_client

            supabase = create_client(config.supabase_url, config.supabase_key)
            result = (
                supabase.table("foodos2_food_items")
                .select("id, name")
                .eq("user_id", uid)
                .in_("kind", ["meal", "snack"])
                .ilike("name", f"%{recipe_name}%")
                .limit(1)
                .execute()
            )

            if not result.data:
                return f"Could not find recipe matching '{recipe_name}'"
            recipe_id = result.data[0]["id"]

        data = await pi_client.get_recipe_details(recipe_id, uid, scale, include_rda=True)

        lines = [f"# {data.get('recipe_name', 'Recipe')}", ""]

        kind = data.get("recipe_kind")
        if kind:
            lines.append(f"*Type: {kind}*")

        if scale != 1.0:
            lines.append(f"*Scaled: {scale}x*")
        lines.append("")

        prep = data.get("prep_time_minutes")
        cook = data.get("cook_time_minutes")
        if prep or cook:
            times = []
            if prep:
                times.append(f"Prep: {prep}min")
            if cook:
                times.append(f"Cook: {cook}min")
            lines.append(f"**Time**: {', '.join(times)}")
            lines.append("")

        ingredients = data.get("ingredients", [])
        if ingredients:
            lines.append("## Ingredients")
            for ing in ingredients:
                name = ing.get("ingredient_name", "Unknown")
                amount = ing.get("amount_g", 0)
                lines.append(f"- {name}: {amount:.0f}g")
            lines.append("")

        steps = data.get("prep_steps", [])
        if steps:
            lines.append("## Instructions")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        nutrition = data.get("nutrition", {})
        if nutrition:
            lines.append("## Nutrition (Total)")
            lines.append(f"- **Calories**: {nutrition.get('total_calories', 0):.0f}")
            lines.append(f"- **Protein**: {nutrition.get('protein_g', 0):.1f}g")
            lines.append(f"- **Carbs**: {nutrition.get('carbs_g', 0):.1f}g")
            lines.append(f"- **Fat**: {nutrition.get('fat_g', 0):.1f}g")

            cal_100 = nutrition.get("calories_per_100g")
            if cal_100:
                lines.append("")
                lines.append(f"*Per 100g: {cal_100:.0f} cal*")

            micros = nutrition.get("top_micronutrients", [])
            if micros:
                lines.append("")
                lines.append("### Top Micronutrients")
                for m in micros[:6]:
                    name = m.get("name")
                    pct = m.get("percent_rda", 0)
                    lines.append(f"- {name}: {pct:.0f}% RDA")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching recipe: {e}"


@mcp.tool()
async def search_usda(
    query: str,
    limit: int = 10,
) -> str:
    """Search USDA FoodData Central for nutrition information.

    Useful for looking up nutrition data for common foods not in your database.

    Args:
        query: Food to search for (e.g., "chicken breast", "brown rice")
        limit: Maximum results (default 10, max 25)

    Returns:
        List of matching foods with nutrition info
    """
    try:
        data = await pi_client.search_usda(query, min(limit, 25))

        foods = data.get("foods", [])
        if not foods:
            return f"No USDA foods found matching '{query}'"

        lines = [f"# USDA Search: '{query}'", ""]
        lines.append(f"Found {data.get('total_hits', len(foods))} results (showing {len(foods)})")
        lines.append("")

        for food in foods:
            name = food.get("description", "Unknown")
            brand = food.get("brandOwner") or food.get("brandName")
            fdc_id = food.get("fdcId")

            lines.append(f"### {name}")
            if brand:
                lines.append(f"*{brand}*")

            nutrients = food.get("foodNutrients", [])
            cal = next((n.get("value", 0) for n in nutrients if n.get("nutrientName") == "Energy"), 0)
            protein = next(
                (n.get("value", 0) for n in nutrients if n.get("nutrientName") == "Protein"), 0
            )
            fat = next(
                (n.get("value", 0) for n in nutrients if "Fat" in n.get("nutrientName", "")), 0
            )
            carbs = next(
                (n.get("value", 0) for n in nutrients if "Carbohydrate" in n.get("nutrientName", "")),
                0,
            )

            lines.append(
                f"Per 100g: {cal:.0f} cal, {protein:.1f}g protein, {carbs:.1f}g carbs, {fat:.1f}g fat"
            )
            if fdc_id:
                lines.append(f"FDC ID: {fdc_id}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching USDA: {e}"


@mcp.tool()
async def lookup_barcode(barcode: str) -> str:
    """Look up a product by barcode (UPC/EAN).

    Args:
        barcode: Product barcode (UPC or EAN)

    Returns:
        Product info with nutrition data if found
    """
    try:
        data = await pi_client.lookup_barcode(barcode)

        if not data or data.get("status") == 0:
            return f"No product found for barcode {barcode}"

        product = data.get("product", data)
        name = product.get("product_name", "Unknown Product")
        brand = product.get("brands", "")

        lines = [f"# {name}", ""]
        if brand:
            lines.append(f"*Brand: {brand}*")
        lines.append(f"Barcode: {barcode}")
        lines.append("")

        nutriments = product.get("nutriments", {})
        if nutriments:
            lines.append("## Nutrition (per 100g)")
            cal = nutriments.get("energy-kcal_100g", nutriments.get("energy_100g", 0))
            protein = nutriments.get("proteins_100g", 0)
            carbs = nutriments.get("carbohydrates_100g", 0)
            fat = nutriments.get("fat_100g", 0)

            lines.append(f"- **Calories**: {cal:.0f}")
            lines.append(f"- **Protein**: {protein:.1f}g")
            lines.append(f"- **Carbs**: {carbs:.1f}g")
            lines.append(f"- **Fat**: {fat:.1f}g")

        nutriscore = product.get("nutriscore_grade")
        if nutriscore:
            lines.append("")
            lines.append(f"**Nutri-Score**: {nutriscore.upper()}")

        allergens = product.get("allergens_tags", [])
        if allergens:
            lines.append("")
            lines.append(f"**Allergens**: {', '.join(a.replace('en:', '') for a in allergens)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error looking up barcode: {e}"


# ============================================================================
# AI TOOLS
# ============================================================================


@mcp.tool()
async def generate_recipe(
    prompt: str,
    mode: str = "lazy",
) -> str:
    """Generate a recipe from a text prompt using AI.

    Args:
        prompt: Description of the recipe to generate (e.g., "high protein chicken stir fry")
        mode: Generation mode:
            - "lazy": Quick, simple recipes (default)
            - "fancy": Gourmet, more elaborate recipes
            - "healthy": Focus on nutritious ingredients

    Returns:
        Generated recipe with ingredients, instructions, and nutrition
    """
    if mode not in ["lazy", "fancy", "healthy"]:
        mode = "lazy"

    try:
        data = await pi_client.generate_recipe(prompt, mode)

        lines = [f"# {data.get('name', 'Generated Recipe')}", ""]

        kind = data.get("kind")
        if kind:
            lines.append(f"*Type: {kind}*")

        description = data.get("description")
        if description:
            lines.append(f"*{description}*")
        lines.append("")

        prep = data.get("prep_time_minutes")
        cook = data.get("cook_time_minutes")
        effort = data.get("effort_score")
        yield_amt = data.get("yield_amount")

        meta = []
        if prep:
            meta.append(f"Prep: {prep}min")
        if cook:
            meta.append(f"Cook: {cook}min")
        if effort:
            meta.append(f"Effort: {effort}/5")
        if yield_amt:
            meta.append(f"Yield: {yield_amt}")
        if meta:
            lines.append(f"**{' | '.join(meta)}**")
            lines.append("")

        oven = data.get("oven_temp_f")
        if oven:
            lines.append(f"Preheat oven to {oven}°F")
            lines.append("")

        ingredients = data.get("ingredients", [])
        if ingredients:
            lines.append("## Ingredients")
            for ing in ingredients:
                if isinstance(ing, dict):
                    name = ing.get("name", "")
                    amount = ing.get("amount_g", ing.get("amount", ""))
                    unit = ing.get("unit", "g")
                    lines.append(f"- {name}: {amount}{unit if amount else ''}")
                else:
                    lines.append(f"- {ing}")
            lines.append("")

        steps = data.get("prep_steps", [])
        if steps:
            lines.append("## Instructions")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        lines.append("---")
        lines.append("*Recipe generated by AI. Review and adjust as needed.*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating recipe: {e}"


@mcp.tool()
async def lookup_nutrition(
    query: str,
    kind: str = "ingredient",
) -> str:
    """Look up nutrition information for any food using AI.

    Useful for finding nutrition data for foods not in your database.

    Args:
        query: Food to look up (e.g., "rotisserie chicken thigh", "avocado toast")
        kind: Expected type: "ingredient", "snack", or "product"

    Returns:
        Nutrition information including macros and suggested micronutrients
    """
    if kind not in ["ingredient", "snack", "product"]:
        kind = "ingredient"

    try:
        data = await pi_client.lookup_nutrition(query, kind)

        lines = [f"# {data.get('name', query)}", ""]

        kind_result = data.get("kind")
        if kind_result:
            lines.append(f"*Type: {kind_result}*")

        serving = data.get("serving_g", 100)
        lines.append(f"*Serving size: {serving}g*")
        lines.append("")

        lines.append("## Nutrition (per 100g)")
        lines.append(f"- **Calories**: {data.get('calories', 0):.0f}")
        lines.append(f"- **Protein**: {data.get('protein_g', 0):.1f}g")
        lines.append(f"- **Carbs**: {data.get('carbs_g', 0):.1f}g")
        lines.append(f"- **Fat**: {data.get('fat_g', 0):.1f}g")

        fiber = data.get("fiber_g")
        if fiber:
            lines.append(f"- **Fiber**: {fiber:.1f}g")
        lines.append("")

        micros = data.get("micronutrients", [])
        if micros:
            lines.append("## Key Micronutrients")
            for m in micros[:8]:
                if isinstance(m, dict):
                    name = m.get("name", "")
                    amount = m.get("amount", 0)
                    unit = m.get("unit", "")
                    lines.append(f"- {name}: {amount}{unit}")
                else:
                    lines.append(f"- {m}")
            lines.append("")

        lines.append("---")
        lines.append("*Nutrition data estimated by AI. Verify for accuracy.*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error looking up nutrition: {e}"


@mcp.tool()
async def generate_prep_steps(
    recipe_name: str,
    ingredients: list[str],
    existing_steps: list[str] | None = None,
) -> str:
    """Generate or improve cooking instructions for a recipe.

    Args:
        recipe_name: Name of the recipe
        ingredients: List of ingredients (e.g., ["500g chicken breast", "2 cups rice"])
        existing_steps: Optional existing steps to improve

    Returns:
        Generated cooking instructions
    """
    try:
        ing_list = [{"name": ing} for ing in ingredients]

        data = await pi_client.generate_prep_steps(recipe_name, ing_list, existing_steps)

        if not data.get("ok"):
            return f"Failed to generate prep steps: {data.get('error', 'Unknown error')}"

        steps = data.get("prep_steps", [])

        lines = [f"# Instructions for {recipe_name}", ""]

        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")

        lines.append("")
        lines.append("---")
        lines.append("*Instructions generated by AI. Adjust times and techniques as needed.*")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating prep steps: {e}"


# Entry point
if __name__ == "__main__":
    mcp.run()
