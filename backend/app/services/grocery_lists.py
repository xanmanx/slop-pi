"""
Grocery lists persistence service.

Provides CRUD operations for saving and managing grocery lists.
"""

import logging
from datetime import datetime
from typing import Optional

from app.models.grocery import (
    GroceryItem,
    GroceryListRecord,
    GroceryListItemRecord,
    SaveGroceryListRequest,
    GroceryListWithItems,
)
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)


async def save_grocery_list(request: SaveGroceryListRequest) -> str:
    """
    Save a generated grocery list to the database.

    Returns the list ID.
    """
    client = get_supabase_client()

    # Create the grocery list record
    list_data = {
        "user_id": request.user_id,
        "name": request.name,
        "start_date": str(request.start_date),
        "end_date": str(request.end_date),
        "include_meals": request.include_meals,
        "include_reorders": request.include_reorders,
        "include_supplements": request.include_supplements,
        "subtract_inventory": request.subtract_inventory,
        "include_household": request.include_household,
        "status": "active",
    }

    result = client.table(TABLES["grocery_lists"]).insert(list_data).execute()
    if not result.data:
        raise ValueError("Failed to create grocery list")

    list_id = result.data[0]["id"]
    logger.info(f"Created grocery list {list_id} for user {request.user_id}")

    # Insert items
    if request.items:
        items_data = []
        for idx, item in enumerate(request.items):
            items_data.append({
                "grocery_list_id": list_id,
                "food_item_id": item.ingredient_id or item.canonical_id,
                "name": item.name,
                "needed_g": item.needed_g,
                "in_stock_g": item.in_stock_g,
                "to_buy_g": item.to_buy_g,
                "from_meals": item.from_meals,
                "from_reorders": item.from_reorders,
                "from_supplements": item.from_supplements,
                "category": item.category.value if hasattr(item.category, 'value') else str(item.category),
                "sort_order": idx,
                "checked": False,
            })

        # Insert in batches of 100
        for i in range(0, len(items_data), 100):
            batch = items_data[i:i + 100]
            client.table(TABLES["grocery_list_items"]).insert(batch).execute()

        logger.info(f"Inserted {len(items_data)} items into grocery list {list_id}")

    return list_id


async def get_grocery_lists(
    user_id: str,
    status: Optional[str] = "active",
    limit: int = 20,
) -> list[GroceryListRecord]:
    """
    Get user's grocery lists with item counts.

    Args:
        user_id: The user's ID
        status: Filter by status (active, completed, archived) or None for all
        limit: Maximum number of lists to return

    Returns:
        List of GroceryListRecord with item counts
    """
    client = get_supabase_client()

    # Build query
    query = client.table(TABLES["grocery_lists"]).select("*").eq("user_id", user_id)

    if status:
        query = query.eq("status", status)

    query = query.order("created_at", desc=True).limit(limit)
    result = query.execute()

    lists = []
    for row in result.data or []:
        # Get item counts
        items_result = (
            client.table(TABLES["grocery_list_items"])
            .select("id, checked")
            .eq("grocery_list_id", row["id"])
            .execute()
        )
        items = items_result.data or []
        item_count = len(items)
        checked_count = sum(1 for item in items if item.get("checked"))

        lists.append(GroceryListRecord(
            id=row["id"],
            user_id=row["user_id"],
            name=row.get("name", "Shopping List"),
            start_date=row["start_date"],
            end_date=row["end_date"],
            status=row.get("status", "active"),
            item_count=item_count,
            checked_count=checked_count,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
            include_meals=row.get("include_meals", True),
            include_reorders=row.get("include_reorders", True),
            include_supplements=row.get("include_supplements", True),
            subtract_inventory=row.get("subtract_inventory", True),
            include_household=row.get("include_household", False),
        ))

    return lists


async def get_grocery_list(
    list_id: str,
    user_id: str,
) -> GroceryListWithItems:
    """
    Get a specific grocery list with all its items.

    Args:
        list_id: The grocery list ID
        user_id: The user's ID (for authorization)

    Returns:
        GroceryListWithItems containing the list and its items

    Raises:
        ValueError: If list not found or not owned by user
    """
    client = get_supabase_client()

    # Get the list
    list_result = (
        client.table(TABLES["grocery_lists"])
        .select("*")
        .eq("id", list_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not list_result.data:
        raise ValueError(f"Grocery list {list_id} not found")

    row = list_result.data

    # Get items
    items_result = (
        client.table(TABLES["grocery_list_items"])
        .select("*")
        .eq("grocery_list_id", list_id)
        .order("sort_order")
        .execute()
    )

    items = []
    for item_row in items_result.data or []:
        items.append(GroceryListItemRecord(
            id=item_row["id"],
            grocery_list_id=item_row["grocery_list_id"],
            food_item_id=item_row.get("food_item_id"),
            name=item_row["name"],
            needed_g=float(item_row.get("needed_g", 0)),
            in_stock_g=float(item_row.get("in_stock_g", 0)),
            to_buy_g=float(item_row.get("to_buy_g", 0)),
            from_meals=float(item_row.get("from_meals", 0)),
            from_reorders=float(item_row.get("from_reorders", 0)),
            from_supplements=float(item_row.get("from_supplements", 0)),
            category=item_row.get("category", "other"),
            sort_order=item_row.get("sort_order", 0),
            checked=item_row.get("checked", False),
            checked_at=item_row.get("checked_at"),
            created_at=item_row.get("created_at"),
        ))

    list_record = GroceryListRecord(
        id=row["id"],
        user_id=row["user_id"],
        name=row.get("name", "Shopping List"),
        start_date=row["start_date"],
        end_date=row["end_date"],
        status=row.get("status", "active"),
        item_count=len(items),
        checked_count=sum(1 for item in items if item.checked),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row.get("completed_at"),
        include_meals=row.get("include_meals", True),
        include_reorders=row.get("include_reorders", True),
        include_supplements=row.get("include_supplements", True),
        subtract_inventory=row.get("subtract_inventory", True),
        include_household=row.get("include_household", False),
    )

    return GroceryListWithItems(list=list_record, items=items)


async def update_item_checked(
    item_id: str,
    checked: bool,
    user_id: str,
) -> bool:
    """
    Toggle an item's checked status.

    Args:
        item_id: The grocery list item ID
        checked: New checked status
        user_id: The user's ID (for authorization)

    Returns:
        True if successful

    Raises:
        ValueError: If item not found or not owned by user
    """
    client = get_supabase_client()

    # Get the item to verify ownership via parent list
    item_result = (
        client.table(TABLES["grocery_list_items"])
        .select("*, grocery_lists!inner(user_id)")
        .eq("id", item_id)
        .single()
        .execute()
    )

    if not item_result.data:
        raise ValueError(f"Grocery list item {item_id} not found")

    # Verify ownership
    if item_result.data.get("grocery_lists", {}).get("user_id") != user_id:
        raise ValueError("Not authorized to update this item")

    # Update the item
    update_data = {
        "checked": checked,
        "checked_at": datetime.utcnow().isoformat() if checked else None,
    }

    client.table(TABLES["grocery_list_items"]).update(update_data).eq("id", item_id).execute()
    logger.info(f"Updated item {item_id} checked={checked}")

    return True


async def delete_grocery_list(list_id: str, user_id: str) -> bool:
    """
    Delete a grocery list and all its items.

    Args:
        list_id: The grocery list ID
        user_id: The user's ID (for authorization)

    Returns:
        True if successful

    Raises:
        ValueError: If list not found or not owned by user
    """
    client = get_supabase_client()

    # Verify ownership
    list_result = (
        client.table(TABLES["grocery_lists"])
        .select("id")
        .eq("id", list_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not list_result.data:
        raise ValueError(f"Grocery list {list_id} not found")

    # Delete (items will cascade)
    client.table(TABLES["grocery_lists"]).delete().eq("id", list_id).execute()
    logger.info(f"Deleted grocery list {list_id}")

    return True


async def complete_grocery_list(list_id: str, user_id: str) -> bool:
    """
    Mark a grocery list as completed.

    Args:
        list_id: The grocery list ID
        user_id: The user's ID (for authorization)

    Returns:
        True if successful

    Raises:
        ValueError: If list not found or not owned by user
    """
    client = get_supabase_client()

    # Verify ownership
    list_result = (
        client.table(TABLES["grocery_lists"])
        .select("id")
        .eq("id", list_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not list_result.data:
        raise ValueError(f"Grocery list {list_id} not found")

    # Update status
    update_data = {
        "status": "completed",
        "completed_at": datetime.utcnow().isoformat(),
    }

    client.table(TABLES["grocery_lists"]).update(update_data).eq("id", list_id).execute()
    logger.info(f"Completed grocery list {list_id}")

    return True


async def archive_grocery_list(list_id: str, user_id: str) -> bool:
    """
    Archive a grocery list.

    Args:
        list_id: The grocery list ID
        user_id: The user's ID (for authorization)

    Returns:
        True if successful
    """
    client = get_supabase_client()

    # Verify ownership
    list_result = (
        client.table(TABLES["grocery_lists"])
        .select("id")
        .eq("id", list_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not list_result.data:
        raise ValueError(f"Grocery list {list_id} not found")

    # Update status
    client.table(TABLES["grocery_lists"]).update({"status": "archived"}).eq("id", list_id).execute()
    logger.info(f"Archived grocery list {list_id}")

    return True
