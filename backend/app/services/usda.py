"""
USDA FoodData Central service with local SQLite caching.

The cache stores full food data locally on the Pi, so after the first lookup
subsequent requests are instant - no network round-trip to USDA.
"""

import json
import logging
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# Nutrient IDs for macros
NUTRIENT_IDS = {
    "energy_kcal": 1008,
    "protein": 1003,
    "fat": 1004,
    "carbs": 1005,
}


class USDAService:
    """USDA FoodData Central service with SQLite cache."""

    def __init__(self):
        self.db_path = Path(settings.usda_cache_db)
        self.db: aiosqlite.Connection | None = None
        self.http: httpx.AsyncClient | None = None

    async def init_cache(self):
        """Initialize the SQLite cache database."""
        # Ensure data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row

        # Create tables
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS foods (
                fdc_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                data_type TEXT,
                brand_owner TEXT,
                calories_per_100g REAL,
                protein_g_per_100g REAL,
                carbs_g_per_100g REAL,
                fat_g_per_100g REAL,
                micronutrients TEXT,  -- JSON
                raw_data TEXT,  -- Full USDA response JSON
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS search_cache (
                query TEXT PRIMARY KEY,
                result_ids TEXT,  -- Comma-separated FDC IDs
                total_hits INTEGER,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_foods_description ON foods(description);
            CREATE INDEX IF NOT EXISTS idx_foods_cached_at ON foods(cached_at);
        """)
        await self.db.commit()

        # Initialize HTTP client
        self.http = httpx.AsyncClient(timeout=30.0)

        logger.info(f"USDA cache initialized at {self.db_path}")

    async def close(self):
        """Close database and HTTP connections."""
        if self.db:
            await self.db.close()
        if self.http:
            await self.http.aclose()

    # =========================================================================
    # Cache Operations
    # =========================================================================

    async def search_cache(self, query: str, limit: int = 25) -> list[dict] | None:
        """Search the local cache for foods matching query."""
        query_lower = query.lower().strip()

        # Check if we have a cached search result
        cursor = await self.db.execute(
            "SELECT result_ids FROM search_cache WHERE query = ?",
            (query_lower,)
        )
        row = await cursor.fetchone()

        if row and row["result_ids"]:
            fdc_ids = row["result_ids"].split(",")[:limit]
            foods = []
            for fdc_id in fdc_ids:
                food = await self.get_cached_food(fdc_id)
                if food:
                    foods.append(food)
            if foods:
                return foods

        # Fallback: search by description
        cursor = await self.db.execute(
            """
            SELECT * FROM foods
            WHERE description LIKE ?
            ORDER BY
                CASE data_type
                    WHEN 'Foundation' THEN 1
                    WHEN 'SR Legacy' THEN 2
                    ELSE 3
                END,
                description
            LIMIT ?
            """,
            (f"%{query_lower}%", limit)
        )
        rows = await cursor.fetchall()

        if rows:
            return [self._row_to_food(r) for r in rows]

        return None

    async def get_cached_food(self, fdc_id: str) -> dict | None:
        """Get a food from cache by FDC ID."""
        cursor = await self.db.execute(
            "SELECT * FROM foods WHERE fdc_id = ?",
            (fdc_id,)
        )
        row = await cursor.fetchone()

        if row:
            # Update last accessed
            await self.db.execute(
                "UPDATE foods SET last_accessed = ? WHERE fdc_id = ?",
                (datetime.utcnow(), fdc_id)
            )
            await self.db.commit()
            return self._row_to_food(row)

        return None

    async def cache_foods(self, foods: list[dict], query: str | None = None):
        """Cache a list of foods from USDA API response."""
        fdc_ids = []

        for food in foods:
            fdc_id = str(food.get("fdcId", ""))
            if not fdc_id:
                continue

            fdc_ids.append(fdc_id)
            macros = self._extract_macros(food.get("foodNutrients", []))
            micros = self._extract_micros(food.get("foodNutrients", []))

            await self.db.execute(
                """
                INSERT OR REPLACE INTO foods
                (fdc_id, description, data_type, brand_owner,
                 calories_per_100g, protein_g_per_100g, carbs_g_per_100g, fat_g_per_100g,
                 micronutrients, raw_data, cached_at, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fdc_id,
                    food.get("description", ""),
                    food.get("dataType", ""),
                    food.get("brandOwner"),
                    macros["kcal"],
                    macros["protein"],
                    macros["carbs"],
                    macros["fat"],
                    json.dumps(micros),
                    json.dumps(food),
                    datetime.utcnow(),
                    datetime.utcnow(),
                )
            )

        # Cache the search query -> results mapping
        if query and fdc_ids:
            await self.db.execute(
                """
                INSERT OR REPLACE INTO search_cache (query, result_ids, total_hits, cached_at)
                VALUES (?, ?, ?, ?)
                """,
                (query.lower().strip(), ",".join(fdc_ids), len(fdc_ids), datetime.utcnow())
            )

        await self.db.commit()
        logger.info(f"Cached {len(fdc_ids)} foods" + (f" for query '{query}'" if query else ""))

    async def cache_single_food(self, food: dict):
        """Cache a single food item."""
        await self.cache_foods([food])

    async def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        cursor = await self.db.execute("SELECT COUNT(*) as count FROM foods")
        foods_count = (await cursor.fetchone())["count"]

        cursor = await self.db.execute("SELECT COUNT(*) as count FROM search_cache")
        queries_count = (await cursor.fetchone())["count"]

        cursor = await self.db.execute(
            "SELECT MIN(cached_at) as oldest, MAX(cached_at) as newest FROM foods"
        )
        row = await cursor.fetchone()

        # Get DB file size
        db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0

        return {
            "foods_cached": foods_count,
            "queries_cached": queries_count,
            "oldest_entry": row["oldest"],
            "newest_entry": row["newest"],
            "db_size_mb": round(db_size_mb, 2),
        }

    async def clear_cache(self, older_than_days: int | None = None) -> int:
        """Clear cache entries, optionally only those older than N days."""
        if older_than_days:
            cutoff = datetime.utcnow() - timedelta(days=older_than_days)
            cursor = await self.db.execute(
                "DELETE FROM foods WHERE cached_at < ?", (cutoff,)
            )
            await self.db.execute(
                "DELETE FROM search_cache WHERE cached_at < ?", (cutoff,)
            )
        else:
            cursor = await self.db.execute("DELETE FROM foods")
            await self.db.execute("DELETE FROM search_cache")

        await self.db.commit()
        return cursor.rowcount

    # =========================================================================
    # USDA API Operations
    # =========================================================================

    async def search_api(
        self,
        query: str,
        page_size: int = 25,
        page_number: int = 1,
        data_types: list[str] | None = None,
    ) -> dict:
        """Search USDA FoodData Central API."""
        if data_types is None:
            data_types = ["Foundation", "SR Legacy"]

        response = await self.http.post(
            f"{USDA_BASE_URL}/foods/search",
            params={"api_key": settings.usda_api_key},
            json={
                "query": query,
                "dataType": data_types,
                "pageSize": page_size,
                "pageNumber": page_number,
                "sortBy": "dataType.keyword",
                "sortOrder": "asc",
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_food_api(self, fdc_id: str) -> dict | None:
        """Get a specific food by FDC ID from USDA API."""
        response = await self.http.get(
            f"{USDA_BASE_URL}/food/{fdc_id}",
            params={"api_key": settings.usda_api_key},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Supabase Integration
    # =========================================================================

    async def resolve_ingredient(self, name: str) -> dict:
        """
        Resolve an ingredient name to the best USDA match.
        Prefers Foundation/SR Legacy over Branded.
        """
        results = await self.search_api(name, page_size=10)
        foods = results.get("foods", [])

        if not foods:
            return {"status": "not_found", "query": name, "candidates": []}

        # Build candidates list
        candidates = []
        for f in foods[:8]:
            macros = self._extract_macros(f.get("foodNutrients", []))
            candidates.append({
                "fdc_id": str(f.get("fdcId", "")),
                "name": f.get("description", ""),
                "data_type": f.get("dataType", ""),
                "macros": macros,
            })

        # Prefer Foundation or SR Legacy
        preferred = next(
            (c for c in candidates if c["data_type"] in ("Foundation", "SR Legacy")),
            None
        )

        if preferred:
            # Cache it
            full_food = await self.get_food_api(preferred["fdc_id"])
            if full_food:
                await self.cache_single_food(full_food)

            return {
                "status": "resolved",
                "resolved": preferred,
                "candidates": candidates[:5],
            }

        return {
            "status": "choose",
            "query": name,
            "candidates": candidates[:5],
        }

    async def import_single_food(self, fdc_id: str) -> dict:
        """Import a specific USDA food to format suitable for Supabase."""
        food = await self.get_food_api(fdc_id)
        if not food:
            return {"error": "Food not found"}

        await self.cache_single_food(food)

        macros = self._extract_macros(food.get("foodNutrients", []))
        micros = self._extract_micros(food.get("foodNutrients", []))

        return {
            "ok": True,
            "food_item": {
                "kind": "ingredient",
                "name": food.get("description", ""),
                "source": "usda",
                "source_id": str(fdc_id),
                "calories_per_100g": macros["kcal"],
                "protein_g_per_100g": macros["protein"],
                "carbs_g_per_100g": macros["carbs"],
                "fat_g_per_100g": macros["fat"],
                "micronutrients": micros,
                "notes": f"source=usda; dataType={food.get('dataType', '')}",
            },
        }

    async def search_and_import(self, query: str, limit: int = 25) -> dict:
        """Search USDA and return foods formatted for Supabase import."""
        results = await self.search_api(query, page_size=limit)
        foods = results.get("foods", [])

        await self.cache_foods(foods, query)

        items = []
        for f in foods:
            macros = self._extract_macros(f.get("foodNutrients", []))
            micros = self._extract_micros(f.get("foodNutrients", []))
            items.append({
                "kind": "ingredient",
                "name": f.get("description", ""),
                "source": "usda",
                "source_id": str(f.get("fdcId", "")),
                "calories_per_100g": macros["kcal"],
                "protein_g_per_100g": macros["protein"],
                "carbs_g_per_100g": macros["carbs"],
                "fat_g_per_100g": macros["fat"],
                "micronutrients": micros,
            })

        return {
            "ok": True,
            "count": len(items),
            "food_items": items,
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_food(self, row: aiosqlite.Row) -> dict:
        """Convert a database row to a food dict."""
        return {
            "fdcId": row["fdc_id"],
            "description": row["description"],
            "dataType": row["data_type"],
            "brandOwner": row["brand_owner"],
            "calories_per_100g": row["calories_per_100g"],
            "protein_g_per_100g": row["protein_g_per_100g"],
            "carbs_g_per_100g": row["carbs_g_per_100g"],
            "fat_g_per_100g": row["fat_g_per_100g"],
            "micronutrients": json.loads(row["micronutrients"]) if row["micronutrients"] else [],
            "cached_at": row["cached_at"],
        }

    def _extract_macros(self, nutrients: list) -> dict:
        """Extract macronutrients from USDA nutrient list."""
        result = {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}

        for n in nutrients:
            nutrient_id = n.get("nutrientId") or n.get("nutrient", {}).get("id")
            value = n.get("value") or n.get("amount", 0)

            if nutrient_id == NUTRIENT_IDS["energy_kcal"]:
                result["kcal"] = float(value or 0)
            elif nutrient_id == NUTRIENT_IDS["protein"]:
                result["protein"] = float(value or 0)
            elif nutrient_id == NUTRIENT_IDS["carbs"]:
                result["carbs"] = float(value or 0)
            elif nutrient_id == NUTRIENT_IDS["fat"]:
                result["fat"] = float(value or 0)

        return result

    def _extract_micros(self, nutrients: list, top_k: int = 12) -> list:
        """Extract top micronutrients from USDA nutrient list."""
        macro_ids = set(NUTRIENT_IDS.values())
        micros = []

        for n in nutrients:
            nutrient_id = n.get("nutrientId") or n.get("nutrient", {}).get("id")
            if nutrient_id in macro_ids:
                continue

            value = n.get("value") or n.get("amount", 0)
            if not value or value <= 0:
                continue

            name = n.get("nutrientName") or n.get("nutrient", {}).get("name", "")
            unit = n.get("unitName") or n.get("nutrient", {}).get("unitName", "")

            # Convert to mg for comparison
            mg_value = self._to_mg(float(value), unit)

            micros.append({
                "nutrient_id": nutrient_id,
                "name": name,
                "unit": unit,
                "amount_per_100g": round(float(value), 4),
                "amount_mg_per_100g": round(mg_value, 6) if mg_value else None,
            })

        # Sort by mg value (descending), nulls last
        micros.sort(key=lambda x: (x["amount_mg_per_100g"] is None, -(x["amount_mg_per_100g"] or 0)))

        return micros[:top_k]

    def _to_mg(self, amount: float, unit: str) -> float | None:
        """Convert nutrient amount to milligrams."""
        unit = unit.lower().strip()
        if unit == "mg":
            return amount
        elif unit in ("µg", "ug", "mcg"):
            return amount / 1000
        elif unit == "g":
            return amount * 1000
        return None
