"""
Open Food Facts barcode lookup service with local SQLite caching.

The cache stores product data locally on the Pi, so after the first lookup
subsequent requests are instant - no network round-trip to Open Food Facts.

API: https://world.openfoodfacts.org/api/v2/product/{barcode}
Rate Limits: None (be respectful, ~1 req/sec recommended)
"""

import json
import logging
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional
import time

import httpx

from app.config import get_settings
from app.models.barcode import (
    ProductInfo,
    NutritionPer100g,
    BarcodeLookupResponse,
    BatchBarcodeLookupResponse,
    BarcodeImportResponse,
    BarcodeCacheStats,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Open Food Facts API
OFF_BASE_URL = "https://world.openfoodfacts.org/api/v2"
OFF_USER_AGENT = "slop-pi/2.2.0 (meal planning app; contact@slxp.app)"


class BarcodeService:
    """Open Food Facts barcode lookup with SQLite cache."""

    def __init__(self):
        # Store barcode cache alongside USDA cache
        data_dir = Path(settings.data_dir)
        self.db_path = data_dir / "barcode_cache.db"
        self.db: Optional[aiosqlite.Connection] = None
        self.http: Optional[httpx.AsyncClient] = None

    async def init_cache(self):
        """Initialize the SQLite cache database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row

        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                barcode TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                brand TEXT,
                quantity TEXT,
                serving_size TEXT,
                serving_size_g REAL,
                categories TEXT,  -- JSON array
                calories_per_100g REAL,
                protein_g_per_100g REAL,
                carbs_g_per_100g REAL,
                fat_g_per_100g REAL,
                fiber_g_per_100g REAL,
                sugar_g_per_100g REAL,
                sodium_mg_per_100g REAL,
                saturated_fat_g_per_100g REAL,
                ingredients_text TEXT,
                allergens TEXT,  -- JSON array
                image_url TEXT,
                image_thumb_url TEXT,
                nutriscore_grade TEXT,
                nova_group INTEGER,
                ecoscore_grade TEXT,
                raw_response TEXT,  -- Full API response JSON
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS not_found (
                barcode TEXT PRIMARY KEY,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
            CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
            CREATE INDEX IF NOT EXISTS idx_products_cached_at ON products(cached_at);
        """)
        await self.db.commit()

        self.http = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": OFF_USER_AGENT}
        )

        logger.info(f"Barcode cache initialized at {self.db_path}")

    async def close(self):
        """Close database and HTTP connections."""
        if self.db:
            await self.db.close()
        if self.http:
            await self.http.aclose()

    # =========================================================================
    # Core Lookup Methods
    # =========================================================================

    async def lookup(self, barcode: str) -> BarcodeLookupResponse:
        """
        Look up a product by barcode.

        Checks local cache first, then hits Open Food Facts API.
        """
        start_time = time.time()
        barcode = self._normalize_barcode(barcode)

        # Check cache first
        cached = await self._get_cached_product(barcode)
        if cached:
            return BarcodeLookupResponse(
                success=True,
                barcode=barcode,
                product=cached,
                source="cache",
                lookup_time_ms=(time.time() - start_time) * 1000
            )

        # Check if we already know this barcode doesn't exist
        if await self._is_known_not_found(barcode):
            return BarcodeLookupResponse(
                success=False,
                barcode=barcode,
                error="Product not found in Open Food Facts",
                source="not_found",
                lookup_time_ms=(time.time() - start_time) * 1000
            )

        # Hit API
        try:
            product = await self._fetch_from_api(barcode)
            if product:
                await self._cache_product(barcode, product)
                return BarcodeLookupResponse(
                    success=True,
                    barcode=barcode,
                    product=product,
                    source="api",
                    lookup_time_ms=(time.time() - start_time) * 1000
                )
            else:
                await self._mark_not_found(barcode)
                return BarcodeLookupResponse(
                    success=False,
                    barcode=barcode,
                    error="Product not found in Open Food Facts",
                    source="not_found",
                    lookup_time_ms=(time.time() - start_time) * 1000
                )
        except Exception as e:
            logger.error(f"Barcode API error for {barcode}: {e}")
            return BarcodeLookupResponse(
                success=False,
                barcode=barcode,
                error=str(e),
                source="api",
                lookup_time_ms=(time.time() - start_time) * 1000
            )

    async def lookup_batch(self, barcodes: list[str]) -> BatchBarcodeLookupResponse:
        """Look up multiple barcodes."""
        start_time = time.time()
        products = []
        not_found = []

        for barcode in barcodes:
            result = await self.lookup(barcode)
            if result.success and result.product:
                products.append(result.product)
            else:
                not_found.append(barcode)

        return BatchBarcodeLookupResponse(
            total_requested=len(barcodes),
            found=len(products),
            not_found=len(not_found),
            products=products,
            not_found_barcodes=not_found,
            lookup_time_ms=(time.time() - start_time) * 1000
        )

    # =========================================================================
    # API Methods
    # =========================================================================

    async def _fetch_from_api(self, barcode: str) -> Optional[ProductInfo]:
        """Fetch product from Open Food Facts API."""
        url = f"{OFF_BASE_URL}/product/{barcode}"
        params = {
            "fields": "code,product_name,brands,quantity,serving_size,serving_quantity,"
                      "categories_tags,nutriments,ingredients_text,allergens_tags,"
                      "image_url,image_small_url,nutriscore_grade,nova_group,ecoscore_grade"
        }

        try:
            response = await self.http.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != 1:
                return None

            product_data = data.get("product", {})
            return self._parse_product(barcode, product_data, data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to fetch barcode {barcode}: {e}")
            raise

    def _parse_product(self, barcode: str, product: dict, raw_response: dict) -> ProductInfo:
        """Parse Open Food Facts response into ProductInfo."""
        nutriments = product.get("nutriments", {})

        # Extract nutrition per 100g
        nutrition = NutritionPer100g(
            calories=self._safe_float(nutriments.get("energy-kcal_100g")),
            protein_g=self._safe_float(nutriments.get("proteins_100g")),
            carbs_g=self._safe_float(nutriments.get("carbohydrates_100g")),
            fat_g=self._safe_float(nutriments.get("fat_100g")),
            fiber_g=self._safe_float(nutriments.get("fiber_100g")),
            sugar_g=self._safe_float(nutriments.get("sugars_100g")),
            sodium_mg=self._safe_float(nutriments.get("sodium_100g", 0)) * 1000,  # g to mg
            saturated_fat_g=self._safe_float(nutriments.get("saturated-fat_100g")),
        )

        # Parse categories
        categories = []
        for cat in product.get("categories_tags", []):
            # Tags are like "en:snacks", extract readable name
            if ":" in cat:
                categories.append(cat.split(":")[-1].replace("-", " ").title())
            else:
                categories.append(cat.replace("-", " ").title())

        # Parse allergens
        allergens = []
        for allergen in product.get("allergens_tags", []):
            if ":" in allergen:
                allergens.append(allergen.split(":")[-1].replace("-", " ").title())
            else:
                allergens.append(allergen.replace("-", " ").title())

        # Parse serving size
        serving_size = product.get("serving_size")
        serving_size_g = self._safe_float(product.get("serving_quantity"))

        return ProductInfo(
            barcode=barcode,
            name=product.get("product_name", "Unknown Product"),
            brand=product.get("brands"),
            quantity=product.get("quantity"),
            serving_size=serving_size,
            serving_size_g=serving_size_g,
            categories=categories[:5],  # Limit to top 5
            nutrition_per_100g=nutrition,
            ingredients_text=product.get("ingredients_text"),
            allergens=allergens,
            image_url=product.get("image_url"),
            image_thumb_url=product.get("image_small_url"),
            nutriscore_grade=product.get("nutriscore_grade"),
            nova_group=product.get("nova_group"),
            ecoscore_grade=product.get("ecoscore_grade"),
            source="api",
        )

    # =========================================================================
    # Cache Methods
    # =========================================================================

    async def _get_cached_product(self, barcode: str) -> Optional[ProductInfo]:
        """Get product from cache."""
        cursor = await self.db.execute(
            "SELECT * FROM products WHERE barcode = ?",
            (barcode,)
        )
        row = await cursor.fetchone()

        if row:
            # Update access stats
            await self.db.execute(
                """UPDATE products
                   SET last_accessed = ?, access_count = access_count + 1
                   WHERE barcode = ?""",
                (datetime.utcnow(), barcode)
            )
            await self.db.commit()
            return self._row_to_product(row)

        return None

    async def _cache_product(self, barcode: str, product: ProductInfo):
        """Cache a product."""
        await self.db.execute(
            """INSERT OR REPLACE INTO products (
                barcode, name, brand, quantity, serving_size, serving_size_g,
                categories, calories_per_100g, protein_g_per_100g, carbs_g_per_100g,
                fat_g_per_100g, fiber_g_per_100g, sugar_g_per_100g, sodium_mg_per_100g,
                saturated_fat_g_per_100g, ingredients_text, allergens,
                image_url, image_thumb_url, nutriscore_grade, nova_group, ecoscore_grade,
                cached_at, last_accessed, access_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                barcode,
                product.name,
                product.brand,
                product.quantity,
                product.serving_size,
                product.serving_size_g,
                json.dumps(product.categories),
                product.nutrition_per_100g.calories,
                product.nutrition_per_100g.protein_g,
                product.nutrition_per_100g.carbs_g,
                product.nutrition_per_100g.fat_g,
                product.nutrition_per_100g.fiber_g,
                product.nutrition_per_100g.sugar_g,
                product.nutrition_per_100g.sodium_mg,
                product.nutrition_per_100g.saturated_fat_g,
                product.ingredients_text,
                json.dumps(product.allergens),
                product.image_url,
                product.image_thumb_url,
                product.nutriscore_grade,
                product.nova_group,
                product.ecoscore_grade,
                datetime.utcnow(),
                datetime.utcnow(),
            )
        )
        await self.db.commit()

        # Remove from not_found if it was there
        await self.db.execute("DELETE FROM not_found WHERE barcode = ?", (barcode,))
        await self.db.commit()

    async def _is_known_not_found(self, barcode: str) -> bool:
        """Check if we already know this barcode doesn't exist."""
        cursor = await self.db.execute(
            "SELECT 1 FROM not_found WHERE barcode = ?",
            (barcode,)
        )
        row = await cursor.fetchone()
        return row is not None

    async def _mark_not_found(self, barcode: str):
        """Mark a barcode as not found (to avoid repeated API calls)."""
        await self.db.execute(
            "INSERT OR REPLACE INTO not_found (barcode, checked_at) VALUES (?, ?)",
            (barcode, datetime.utcnow())
        )
        await self.db.commit()

    def _row_to_product(self, row: aiosqlite.Row) -> ProductInfo:
        """Convert database row to ProductInfo."""
        categories = json.loads(row["categories"]) if row["categories"] else []
        allergens = json.loads(row["allergens"]) if row["allergens"] else []

        return ProductInfo(
            barcode=row["barcode"],
            name=row["name"],
            brand=row["brand"],
            quantity=row["quantity"],
            serving_size=row["serving_size"],
            serving_size_g=row["serving_size_g"],
            categories=categories,
            nutrition_per_100g=NutritionPer100g(
                calories=row["calories_per_100g"] or 0,
                protein_g=row["protein_g_per_100g"] or 0,
                carbs_g=row["carbs_g_per_100g"] or 0,
                fat_g=row["fat_g_per_100g"] or 0,
                fiber_g=row["fiber_g_per_100g"] or 0,
                sugar_g=row["sugar_g_per_100g"] or 0,
                sodium_mg=row["sodium_mg_per_100g"] or 0,
                saturated_fat_g=row["saturated_fat_g_per_100g"] or 0,
            ),
            ingredients_text=row["ingredients_text"],
            allergens=allergens,
            image_url=row["image_url"],
            image_thumb_url=row["image_thumb_url"],
            nutriscore_grade=row["nutriscore_grade"],
            nova_group=row["nova_group"],
            ecoscore_grade=row["ecoscore_grade"],
            source="cache",
            cached_at=row["cached_at"],
        )

    # =========================================================================
    # Import to Supabase
    # =========================================================================

    async def import_to_supabase(
        self,
        barcode: str,
        user_id: str,
        override_name: Optional[str] = None,
        override_serving_g: Optional[float] = None,
        kind: str = "product",
        add_to_inventory: bool = False,
        inventory_quantity_g: Optional[float] = None,
    ) -> BarcodeImportResponse:
        """Import barcode product as a food item in Supabase."""
        from app.services.supabase import get_supabase_client, TABLES

        # Look up the product first
        result = await self.lookup(barcode)
        if not result.success or not result.product:
            return BarcodeImportResponse(
                success=False,
                barcode=barcode,
                error=result.error or "Product not found"
            )

        product = result.product
        client = get_supabase_client()

        # Determine serving size
        serving_g = override_serving_g or product.serving_size_g or 100.0

        # Create food item
        food_item = {
            "user_id": user_id,
            "name": override_name or product.name,
            "kind": kind,
            "serving_g": serving_g,
            "calories_per_100g": product.nutrition_per_100g.calories,
            "protein_g_per_100g": product.nutrition_per_100g.protein_g,
            "carbs_g_per_100g": product.nutrition_per_100g.carbs_g,
            "fat_g_per_100g": product.nutrition_per_100g.fat_g,
            "fiber_g_per_100g": product.nutrition_per_100g.fiber_g,
            "sugar_g_per_100g": product.nutrition_per_100g.sugar_g,
            "sodium_mg_per_100g": product.nutrition_per_100g.sodium_mg,
            "saturated_fat_g_per_100g": product.nutrition_per_100g.saturated_fat_g,
            "brand": product.brand,
            "barcode": barcode,
            "image_url": product.image_url,
        }

        try:
            # Insert food item
            response = client.table(TABLES["items"]).insert(food_item).execute()
            food_item_id = response.data[0]["id"]
            food_item_name = response.data[0]["name"]

            inventory_item_id = None

            # Optionally add to inventory
            if add_to_inventory and inventory_quantity_g:
                inv_response = client.table(TABLES["inventory"]).insert({
                    "user_id": user_id,
                    "food_item_id": food_item_id,
                    "quantity_g": inventory_quantity_g,
                }).execute()
                inventory_item_id = inv_response.data[0]["id"] if inv_response.data else None

            return BarcodeImportResponse(
                success=True,
                barcode=barcode,
                food_item_id=food_item_id,
                food_item_name=food_item_name,
                added_to_inventory=add_to_inventory and inventory_item_id is not None,
                inventory_item_id=inventory_item_id,
            )

        except Exception as e:
            logger.error(f"Failed to import barcode {barcode}: {e}")
            return BarcodeImportResponse(
                success=False,
                barcode=barcode,
                error=str(e)
            )

    # =========================================================================
    # Cache Management
    # =========================================================================

    async def get_cache_stats(self) -> BarcodeCacheStats:
        """Get cache statistics."""
        cursor = await self.db.execute("SELECT COUNT(*) as total FROM products")
        row = await cursor.fetchone()
        total = row["total"] if row else 0

        cursor = await self.db.execute(
            "SELECT MIN(cached_at) as oldest, MAX(cached_at) as newest FROM products"
        )
        row = await cursor.fetchone()
        oldest = row["oldest"] if row else None
        newest = row["newest"] if row else None

        # Get file size
        size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0

        return BarcodeCacheStats(
            total_cached=total,
            cache_size_mb=round(size_mb, 2),
            oldest_entry=oldest,
            newest_entry=newest,
        )

    async def clear_cache(self, older_than_days: Optional[int] = None):
        """Clear cache, optionally only entries older than N days."""
        if older_than_days:
            cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0)
            cutoff = cutoff.replace(day=cutoff.day - older_than_days)
            await self.db.execute(
                "DELETE FROM products WHERE cached_at < ?",
                (cutoff,)
            )
            await self.db.execute(
                "DELETE FROM not_found WHERE checked_at < ?",
                (cutoff,)
            )
        else:
            await self.db.execute("DELETE FROM products")
            await self.db.execute("DELETE FROM not_found")

        await self.db.commit()
        await self.db.execute("VACUUM")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _normalize_barcode(self, barcode: str) -> str:
        """Normalize barcode format."""
        # Remove any non-digit characters
        return "".join(c for c in barcode if c.isdigit())

    def _safe_float(self, value) -> float:
        """Safely convert value to float."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


# Singleton instance
_barcode_service: Optional[BarcodeService] = None


async def get_barcode_service() -> BarcodeService:
    """Get the barcode service singleton."""
    global _barcode_service
    if _barcode_service is None:
        _barcode_service = BarcodeService()
        await _barcode_service.init_cache()
    return _barcode_service
