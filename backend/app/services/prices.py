"""
Price tracking service for food cost analysis.

Tracks prices over time, analyzes trends, and identifies best deals.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from collections import defaultdict

from app.config import get_settings
from app.models.prices import (
    PriceEntry,
    PriceRecordResponse,
    PriceHistory,
    PriceTrend,
    PriceComparison,
    StorePrice,
    PriceAlert,
    PriceAlertsResponse,
    PriceStatsResponse,
)
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)
settings = get_settings()


class PriceService:
    """Price tracking and analysis service."""

    def __init__(self):
        self.client = get_supabase_client()

    async def record_price(
        self,
        user_id: str,
        food_item_id: str,
        price: Decimal,
        quantity_g: Optional[Decimal] = None,
        store_name: Optional[str] = None,
        receipt_id: Optional[str] = None,
        source: str = "manual",
        purchase_date: Optional[date] = None,
    ) -> PriceRecordResponse:
        """
        Record a price for a food item.

        Calculates price per 100g if quantity is provided.
        """
        try:
            # Calculate price per 100g
            price_per_100g = None
            if quantity_g and quantity_g > 0:
                price_per_100g = (price / quantity_g) * 100

            # Get previous lowest price
            previous_lowest = await self._get_lowest_price(user_id, food_item_id)

            # Insert price record
            price_data = {
                "user_id": user_id,
                "food_item_id": food_item_id,
                "price": float(price),
                "price_per_100g": float(price_per_100g) if price_per_100g else None,
                "quantity_g": float(quantity_g) if quantity_g else None,
                "store_name": store_name,
                "receipt_id": receipt_id,
                "source": source,
                "recorded_at": (purchase_date or date.today()).isoformat(),
            }

            result = self.client.table("price_history").insert(price_data).execute()
            price_id = result.data[0]["id"]

            # Check if this is the new lowest price
            is_lowest = previous_lowest is None or price < previous_lowest

            return PriceRecordResponse(
                success=True,
                price_id=price_id,
                price_per_100g=price_per_100g,
                is_lowest_price=is_lowest,
                previous_lowest=previous_lowest,
            )

        except Exception as e:
            logger.error(f"Error recording price: {e}")
            return PriceRecordResponse(
                success=False,
                error=str(e),
            )

    async def _get_lowest_price(self, user_id: str, food_item_id: str) -> Optional[Decimal]:
        """Get the lowest recorded price for an item."""
        result = (
            self.client.table("price_history")
            .select("price")
            .eq("user_id", user_id)
            .eq("food_item_id", food_item_id)
            .order("price")
            .limit(1)
            .execute()
        )

        if result.data:
            return Decimal(str(result.data[0]["price"]))
        return None

    async def get_price_history(
        self,
        user_id: str,
        food_item_id: str,
        days: int = 90,
    ) -> PriceHistory:
        """Get price history for a food item."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        # Get food item name
        item_result = self.client.table(TABLES["items"]).select("name").eq("id", food_item_id).single().execute()
        food_item_name = item_result.data["name"] if item_result.data else "Unknown"

        # Get price entries
        result = (
            self.client.table("price_history")
            .select("*")
            .eq("user_id", user_id)
            .eq("food_item_id", food_item_id)
            .gte("recorded_at", cutoff)
            .order("recorded_at", desc=True)
            .execute()
        )

        entries = [PriceEntry(**data) for data in (result.data or [])]

        # Calculate statistics
        if entries:
            prices = [e.price for e in entries]
            lowest_price = min(prices)
            highest_price = max(prices)
            average_price = sum(prices) / len(prices)

            # Find store with lowest price
            lowest_entry = min(entries, key=lambda e: e.price)
            lowest_store = lowest_entry.store_name
        else:
            lowest_price = highest_price = average_price = None
            lowest_store = None

        return PriceHistory(
            food_item_id=food_item_id,
            food_item_name=food_item_name,
            entries=entries,
            lowest_price=lowest_price,
            lowest_price_store=lowest_store,
            highest_price=highest_price,
            average_price=Decimal(str(round(average_price, 2))) if average_price else None,
            price_count=len(entries),
        )

    async def analyze_trend(
        self,
        user_id: str,
        food_item_id: str,
        days: int = 30,
    ) -> PriceTrend:
        """Analyze price trend using linear regression."""
        history = await self.get_price_history(user_id, food_item_id, days)

        if len(history.entries) < 2:
            return PriceTrend(
                food_item_id=food_item_id,
                food_item_name=history.food_item_name,
                trend_direction="stable",
                trend_percent=0,
                confidence=0,
                data_points=len(history.entries),
            )

        try:
            from scipy import stats
            import numpy as np

            # Prepare data
            prices = [float(e.price) for e in reversed(history.entries)]
            x = np.arange(len(prices))
            y = np.array(prices)

            # Linear regression
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

            # Calculate trend
            if len(prices) > 0 and prices[0] > 0:
                trend_percent = (slope * len(prices)) / prices[0] * 100
            else:
                trend_percent = 0

            # Determine direction
            if slope > 0.01:
                direction = "up"
            elif slope < -0.01:
                direction = "down"
            else:
                direction = "stable"

            # Get current and old price
            current_price = Decimal(str(prices[-1])) if prices else None
            old_price = Decimal(str(prices[0])) if prices else None

            # Predict next price
            predicted_next = intercept + slope * len(prices)
            predicted_next = Decimal(str(round(max(0, predicted_next), 2)))

            return PriceTrend(
                food_item_id=food_item_id,
                food_item_name=history.food_item_name,
                trend_direction=direction,
                trend_percent=round(trend_percent, 1),
                confidence=abs(r_value),
                current_price=current_price,
                price_30_days_ago=old_price,
                predicted_next_price=predicted_next,
                data_points=len(prices),
            )

        except ImportError:
            logger.warning("scipy not installed, using simple trend calculation")
            # Fallback without scipy
            prices = [float(e.price) for e in reversed(history.entries)]
            if len(prices) >= 2:
                change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] > 0 else 0
                direction = "up" if change > 5 else "down" if change < -5 else "stable"
            else:
                change = 0
                direction = "stable"

            return PriceTrend(
                food_item_id=food_item_id,
                food_item_name=history.food_item_name,
                trend_direction=direction,
                trend_percent=round(change, 1),
                confidence=0.5,
                current_price=Decimal(str(prices[-1])) if prices else None,
                data_points=len(prices),
            )

    async def compare_prices(
        self,
        user_id: str,
        food_item_id: str,
    ) -> PriceComparison:
        """Compare prices across stores."""
        # Get food item name
        item_result = self.client.table(TABLES["items"]).select("name").eq("id", food_item_id).single().execute()
        food_item_name = item_result.data["name"] if item_result.data else "Unknown"

        # Get all prices grouped by store
        result = (
            self.client.table("price_history")
            .select("*")
            .eq("user_id", user_id)
            .eq("food_item_id", food_item_id)
            .not_.is_("store_name", "null")
            .order("recorded_at", desc=True)
            .execute()
        )

        # Group by store
        by_store: dict[str, list] = defaultdict(list)
        for entry in result.data or []:
            store = entry["store_name"]
            if store:
                by_store[store].append(entry)

        stores = []
        for store_name, entries in by_store.items():
            latest = entries[0]
            stores.append(StorePrice(
                store_name=store_name,
                latest_price=Decimal(str(latest["price"])),
                price_per_100g=Decimal(str(latest["price_per_100g"])) if latest.get("price_per_100g") else None,
                last_seen=datetime.fromisoformat(latest["recorded_at"]),
                price_count=len(entries),
            ))

        # Sort by price
        stores.sort(key=lambda s: s.latest_price)

        # Calculate potential savings
        best_value_store = stores[0].store_name if stores else None
        potential_savings = None
        if len(stores) >= 2:
            potential_savings = stores[-1].latest_price - stores[0].latest_price

        return PriceComparison(
            food_item_id=food_item_id,
            food_item_name=food_item_name,
            stores=stores,
            best_value_store=best_value_store,
            potential_savings=potential_savings,
        )

    async def get_price_alerts(
        self,
        user_id: str,
        min_drop_percent: float = 10,
        days: int = 7,
    ) -> PriceAlertsResponse:
        """Get recent price drop alerts."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        # Get recent prices
        recent_result = (
            self.client.table("price_history")
            .select("*, food_item:foodos2_food_items(name)")
            .eq("user_id", user_id)
            .gte("recorded_at", cutoff)
            .order("recorded_at", desc=True)
            .execute()
        )

        # Group by food item
        by_item: dict[str, list] = defaultdict(list)
        for entry in recent_result.data or []:
            by_item[entry["food_item_id"]].append(entry)

        alerts = []
        for food_item_id, entries in by_item.items():
            if len(entries) < 2:
                continue

            # Get latest and previous
            current = entries[0]
            previous = entries[1]

            current_price = Decimal(str(current["price"]))
            previous_price = Decimal(str(previous["price"]))

            if previous_price > 0:
                drop_percent = float((previous_price - current_price) / previous_price * 100)

                if drop_percent >= min_drop_percent:
                    food_name = current.get("food_item", {}).get("name", "Unknown")
                    alerts.append(PriceAlert(
                        food_item_id=food_item_id,
                        food_item_name=food_name,
                        store_name=current.get("store_name", "Unknown"),
                        current_price=current_price,
                        previous_price=previous_price,
                        drop_percent=round(drop_percent, 1),
                        recorded_at=datetime.fromisoformat(current["recorded_at"]),
                    ))

        # Sort by drop percent
        alerts.sort(key=lambda a: a.drop_percent, reverse=True)

        return PriceAlertsResponse(
            alerts=alerts[:20],  # Limit to 20
            alert_count=len(alerts),
        )

    async def get_stats(self, user_id: str) -> PriceStatsResponse:
        """Get price tracking statistics."""
        result = (
            self.client.table("price_history")
            .select("food_item_id, store_name, price")
            .eq("user_id", user_id)
            .execute()
        )

        entries = result.data or []

        unique_items = len(set(e["food_item_id"] for e in entries))
        unique_stores = len(set(e["store_name"] for e in entries if e.get("store_name")))

        # Count store occurrences to find best value store
        store_counts: dict[str, int] = defaultdict(int)
        for e in entries:
            if e.get("store_name"):
                store_counts[e["store_name"]] += 1

        best_value_store = max(store_counts.items(), key=lambda x: x[1])[0] if store_counts else None

        return PriceStatsResponse(
            total_prices_recorded=len(entries),
            unique_items_tracked=unique_items,
            unique_stores=unique_stores,
            best_value_store=best_value_store,
        )


# Singleton
_price_service: Optional[PriceService] = None


def get_price_service() -> PriceService:
    """Get price service singleton."""
    global _price_service
    if _price_service is None:
        _price_service = PriceService()
    return _price_service
