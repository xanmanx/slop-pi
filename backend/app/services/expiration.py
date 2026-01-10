"""
Expiration date management service.

Tracks expiration dates, suggests shelf life based on food categories,
and learns from user corrections.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Literal
from collections import defaultdict

from app.config import get_settings
from app.models.expiration import (
    ShelfLifeInfo,
    InventoryExpiration,
    ExpirationSetResponse,
    ExpiringItemsResponse,
    ShelfLifeCorrection,
    ShelfLifeCorrectionResponse,
    CategoryDefaultsResponse,
    ExpirationStatsResponse,
)
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)
settings = get_settings()


class ExpirationService:
    """Expiration date management and shelf life prediction."""

    def __init__(self):
        self.shelf_life_data = self._load_shelf_life_data()

    def _load_shelf_life_data(self) -> dict:
        """Load shelf life data from JSON file."""
        data_file = Path(__file__).parent.parent / "data" / "shelf_life.json"
        try:
            with open(data_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load shelf life data: {e}")
            return {"categories": {}}

    def get_shelf_life(
        self,
        category: str,
        subcategory: Optional[str] = None,
        storage_type: Literal["pantry", "refrigerator", "freezer"] = "refrigerator",
    ) -> Optional[int]:
        """Get shelf life in days for a category/subcategory."""
        categories = self.shelf_life_data.get("categories", {})

        # Try exact match first
        if category in categories:
            cat_data = categories[category]
            if subcategory and subcategory in cat_data:
                item_data = cat_data[subcategory]
            else:
                # Use first item as default for category
                item_data = next(iter(cat_data.values())) if cat_data else {}

            key = f"{storage_type}_days"
            return item_data.get(key)

        # Try fuzzy match
        for cat_name, cat_data in categories.items():
            if category.lower() in cat_name.lower() or cat_name.lower() in category.lower():
                for item_name, item_data in cat_data.items():
                    if subcategory and (subcategory.lower() in item_name.lower() or item_name.lower() in subcategory.lower()):
                        key = f"{storage_type}_days"
                        return item_data.get(key)
                # Return first match
                first_item = next(iter(cat_data.values())) if cat_data else {}
                key = f"{storage_type}_days"
                return first_item.get(key)

        return None

    def suggest_expiration(
        self,
        food_item_name: str,
        food_item_kind: str,
        purchase_date: Optional[date] = None,
        storage_type: Literal["pantry", "refrigerator", "freezer"] = "refrigerator",
    ) -> Optional[date]:
        """Suggest an expiration date based on food item."""
        purchase = purchase_date or date.today()

        # Map food kinds to categories
        kind_category_map = {
            "ingredient": None,  # Need to guess from name
            "meal": "prepared_meals",
            "snack": "pantry_staples",
            "product": None,  # Need to guess from name
        }

        category = kind_category_map.get(food_item_kind)

        # Try to infer category from name
        if not category:
            name_lower = food_item_name.lower()
            if any(w in name_lower for w in ["milk", "cheese", "yogurt", "cream", "butter", "egg"]):
                category = "dairy"
            elif any(w in name_lower for w in ["chicken", "beef", "pork", "meat", "bacon", "sausage"]):
                category = "meat"
            elif any(w in name_lower for w in ["fish", "salmon", "shrimp", "tuna"]):
                category = "seafood"
            elif any(w in name_lower for w in ["apple", "banana", "orange", "berry", "grape", "fruit"]):
                category = "produce_fruits"
            elif any(w in name_lower for w in ["lettuce", "spinach", "carrot", "broccoli", "vegetable"]):
                category = "produce_vegetables"
            elif any(w in name_lower for w in ["bread", "bagel", "tortilla", "muffin"]):
                category = "bread_bakery"
            elif any(w in name_lower for w in ["juice", "coffee", "tea", "soda", "wine", "beer"]):
                category = "beverages"
            elif any(w in name_lower for w in ["ketchup", "mustard", "sauce", "dressing"]):
                category = "condiments"
            else:
                # Default based on storage
                if storage_type == "freezer":
                    return purchase + timedelta(days=90)
                elif storage_type == "pantry":
                    return purchase + timedelta(days=180)
                else:
                    return purchase + timedelta(days=7)

        # Get shelf life
        shelf_days = self.get_shelf_life(category, storage_type=storage_type)

        if shelf_days:
            return purchase + timedelta(days=shelf_days)

        # Default fallbacks
        defaults = {"pantry": 180, "refrigerator": 7, "freezer": 90}
        return purchase + timedelta(days=defaults.get(storage_type, 7))

    def get_status(self, days_until_expiry: Optional[int]) -> Literal["fresh", "use_soon", "expiring", "expired"]:
        """Get expiration status from days until expiry."""
        if days_until_expiry is None:
            return "fresh"
        if days_until_expiry < 0:
            return "expired"
        if days_until_expiry <= 2:
            return "expiring"
        if days_until_expiry <= 7:
            return "use_soon"
        return "fresh"

    async def get_inventory_with_expiration(
        self,
        user_id: str,
        include_no_expiration: bool = True,
    ) -> list[InventoryExpiration]:
        """Get inventory items with expiration info, sorted by expiration date."""
        client = get_supabase_client()

        query = (
            client.table(TABLES["inventory"])
            .select("*, food_item:foodos2_food_items(id, name, kind)")
            .eq("user_id", user_id)
            .gt("quantity_g", 0)
        )

        if not include_no_expiration:
            query = query.not_.is_("expiration_date", "null")

        result = query.order("expiration_date", nullsfirst=False).execute()

        today = date.today()
        items = []

        for inv in result.data or []:
            food_item = inv.get("food_item", {})

            exp_date = None
            days_until = None
            if inv.get("expiration_date"):
                exp_date = date.fromisoformat(inv["expiration_date"])
                days_until = (exp_date - today).days

            # Get suggested expiration if none set
            suggested = None
            if not exp_date:
                purchase = date.fromisoformat(inv["purchase_date"]) if inv.get("purchase_date") else None
                storage = inv.get("storage_type", "refrigerator")
                suggested = self.suggest_expiration(
                    food_item.get("name", ""),
                    food_item.get("kind", "ingredient"),
                    purchase,
                    storage,
                )

            items.append(InventoryExpiration(
                inventory_id=inv["id"],
                food_item_id=inv["food_item_id"],
                food_item_name=food_item.get("name", "Unknown"),
                food_item_kind=food_item.get("kind", "ingredient"),
                quantity_g=inv["quantity_g"],
                storage_type=inv.get("storage_type", "refrigerator"),
                purchase_date=date.fromisoformat(inv["purchase_date"]) if inv.get("purchase_date") else None,
                expiration_date=exp_date,
                days_until_expiry=days_until,
                status=self.get_status(days_until),
                suggested_expiration=suggested,
            ))

        return items

    async def get_expiring_soon(
        self,
        user_id: str,
        days: int = 7,
    ) -> ExpiringItemsResponse:
        """Get items expiring within N days."""
        all_items = await self.get_inventory_with_expiration(user_id, include_no_expiration=False)

        expiring = [i for i in all_items if i.days_until_expiry is not None and 0 <= i.days_until_expiry <= days]
        expired = [i for i in all_items if i.days_until_expiry is not None and i.days_until_expiry < 0]

        # Sort by days until expiry
        expiring.sort(key=lambda i: i.days_until_expiry or 999)

        return ExpiringItemsResponse(
            items=expiring + expired,
            expiring_count=len(expiring),
            expired_count=len(expired),
        )

    async def set_expiration(
        self,
        user_id: str,
        inventory_id: str,
        expiration_date: Optional[date] = None,
        purchase_date: Optional[date] = None,
        storage_type: Optional[str] = None,
        use_suggested: bool = False,
    ) -> ExpirationSetResponse:
        """Set or update expiration date for an inventory item."""
        client = get_supabase_client()

        try:
            # Get current item
            item_result = (
                client.table(TABLES["inventory"])
                .select("*, food_item:foodos2_food_items(name, kind)")
                .eq("id", inventory_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )

            if not item_result.data:
                return ExpirationSetResponse(
                    success=False,
                    inventory_id=inventory_id,
                    error="Inventory item not found",
                )

            item = item_result.data
            food_item = item.get("food_item", {})

            # Determine expiration date
            if use_suggested:
                purchase = purchase_date or (
                    date.fromisoformat(item["purchase_date"]) if item.get("purchase_date") else date.today()
                )
                storage = storage_type or item.get("storage_type", "refrigerator")
                expiration_date = self.suggest_expiration(
                    food_item.get("name", ""),
                    food_item.get("kind", "ingredient"),
                    purchase,
                    storage,
                )

            # Build update
            update_data = {}
            if expiration_date:
                update_data["expiration_date"] = expiration_date.isoformat()
            if purchase_date:
                update_data["purchase_date"] = purchase_date.isoformat()
            if storage_type:
                update_data["storage_type"] = storage_type

            if not update_data:
                return ExpirationSetResponse(
                    success=False,
                    inventory_id=inventory_id,
                    error="No updates provided",
                )

            # Update
            client.table(TABLES["inventory"]).update(update_data).eq("id", inventory_id).execute()

            # Calculate days until expiry
            days_until = None
            if expiration_date:
                days_until = (expiration_date - date.today()).days

            return ExpirationSetResponse(
                success=True,
                inventory_id=inventory_id,
                expiration_date=expiration_date,
                days_until_expiry=days_until,
                status=self.get_status(days_until),
            )

        except Exception as e:
            logger.error(f"Error setting expiration: {e}")
            return ExpirationSetResponse(
                success=False,
                inventory_id=inventory_id,
                error=str(e),
            )

    async def record_correction(
        self,
        user_id: str,
        food_item_id: str,
        storage_type: str,
        expected_days: int,
        actual_days: int,
    ) -> ShelfLifeCorrectionResponse:
        """Record a shelf life correction for learning."""
        client = get_supabase_client()

        try:
            # Get food item category
            item_result = client.table(TABLES["items"]).select("name, kind").eq("id", food_item_id).single().execute()
            food_item = item_result.data or {}

            # Infer category from name
            name = food_item.get("name", "").lower()
            category = "unknown"
            if any(w in name for w in ["milk", "cheese", "yogurt"]):
                category = "dairy"
            elif any(w in name for w in ["chicken", "beef", "pork"]):
                category = "meat"
            # ... could add more

            correction_data = {
                "user_id": user_id,
                "food_item_id": food_item_id,
                "category": category,
                "storage_type": storage_type,
                "expected_days": expected_days,
                "actual_days": actual_days,
            }

            result = client.table("shelf_life_corrections").insert(correction_data).execute()

            # Calculate updated estimate (simple average of corrections)
            corrections_result = (
                client.table("shelf_life_corrections")
                .select("actual_days")
                .eq("food_item_id", food_item_id)
                .eq("storage_type", storage_type)
                .execute()
            )

            corrections = corrections_result.data or []
            if corrections:
                avg_days = sum(c["actual_days"] for c in corrections) / len(corrections)
                updated_estimate = int(avg_days)
            else:
                updated_estimate = actual_days

            return ShelfLifeCorrectionResponse(
                success=True,
                correction_id=result.data[0]["id"] if result.data else None,
                updated_estimate=updated_estimate,
            )

        except Exception as e:
            logger.error(f"Error recording correction: {e}")
            return ShelfLifeCorrectionResponse(
                success=False,
                error=str(e),
            )

    def get_category_defaults(self, category: str) -> CategoryDefaultsResponse:
        """Get default shelf life for a category."""
        categories = self.shelf_life_data.get("categories", {})

        # Find matching category
        cat_data = None
        matched_category = category

        if category in categories:
            cat_data = categories[category]
        else:
            # Fuzzy match
            for cat_name, data in categories.items():
                if category.lower() in cat_name.lower() or cat_name.lower() in category.lower():
                    cat_data = data
                    matched_category = cat_name
                    break

        if not cat_data:
            return CategoryDefaultsResponse(
                category=category,
                source="not_found",
            )

        # Get subcategories
        subcategories = []
        pantry_days = None
        refrigerator_days = None
        freezer_days = None

        for item_name, item_data in cat_data.items():
            subcategories.append(ShelfLifeInfo(
                category=matched_category,
                subcategory=item_name,
                pantry_days=item_data.get("pantry_days"),
                refrigerator_days=item_data.get("refrigerator_days"),
                freezer_days=item_data.get("freezer_days"),
            ))

            # Use first item as category defaults
            if pantry_days is None:
                pantry_days = item_data.get("pantry_days")
            if refrigerator_days is None:
                refrigerator_days = item_data.get("refrigerator_days")
            if freezer_days is None:
                freezer_days = item_data.get("freezer_days")

        return CategoryDefaultsResponse(
            category=matched_category,
            pantry_days=pantry_days,
            refrigerator_days=refrigerator_days,
            freezer_days=freezer_days,
            subcategories=subcategories,
        )

    async def get_stats(self, user_id: str) -> ExpirationStatsResponse:
        """Get expiration tracking statistics."""
        items = await self.get_inventory_with_expiration(user_id)

        items_with_exp = [i for i in items if i.expiration_date]
        expiring_this_week = [i for i in items_with_exp if i.days_until_expiry is not None and 0 <= i.days_until_expiry <= 7]
        expired = [i for i in items_with_exp if i.days_until_expiry is not None and i.days_until_expiry < 0]

        # Average days to expiry
        valid_days = [i.days_until_expiry for i in items_with_exp if i.days_until_expiry is not None and i.days_until_expiry >= 0]
        avg_days = sum(valid_days) / len(valid_days) if valid_days else None

        # Waste prevention score (100 = nothing expired, 0 = everything expired)
        total_with_exp = len(items_with_exp)
        if total_with_exp > 0:
            waste_score = 100 * (1 - len(expired) / total_with_exp)
        else:
            waste_score = 100

        return ExpirationStatsResponse(
            items_with_expiration=len(items_with_exp),
            items_expiring_this_week=len(expiring_this_week),
            items_expired=len(expired),
            average_days_to_expiry=round(avg_days, 1) if avg_days else None,
            waste_prevention_score=round(waste_score, 1),
        )


# Singleton
_expiration_service: Optional[ExpirationService] = None


def get_expiration_service() -> ExpirationService:
    """Get expiration service singleton."""
    global _expiration_service
    if _expiration_service is None:
        _expiration_service = ExpirationService()
    return _expiration_service
