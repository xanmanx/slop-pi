"""
Unit tests for barcode service.

Tests:
- Barcode normalization
- Cache behavior (mocked)
- Open Food Facts response parsing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from app.services.barcode import BarcodeService
from app.models.barcode import ProductInfo, NutritionPer100g


class TestBarcodeService:
    """Tests for barcode lookup service."""

    @pytest.fixture
    def service(self):
        """Create service instance (not initialized)."""
        return BarcodeService()

    # Barcode Normalization
    @pytest.mark.unit
    def test_normalize_barcode_digits_only(self, service):
        """Should strip non-digit characters."""
        assert service._normalize_barcode("012-345-678-905") == "012345678905"
        assert service._normalize_barcode("012 345 678 905") == "012345678905"
        assert service._normalize_barcode("012345678905") == "012345678905"

    @pytest.mark.unit
    def test_normalize_barcode_with_letters(self, service):
        """Should remove letters from barcode."""
        assert service._normalize_barcode("UPC012345678905") == "012345678905"

    @pytest.mark.unit
    def test_safe_float_conversion(self, service):
        """Should safely convert various values to float."""
        assert service._safe_float(10) == 10.0
        assert service._safe_float("10.5") == 10.5
        assert service._safe_float(None) == 0.0
        assert service._safe_float("invalid") == 0.0

    # Product Parsing
    @pytest.mark.unit
    def test_parse_product_basic(self, service):
        """Should parse basic product data from OFF response."""
        raw_response = {"product": {}}
        product_data = {
            "product_name": "Test Product",
            "brands": "Test Brand",
            "quantity": "500g",
            "nutriments": {
                "energy-kcal_100g": 100,
                "proteins_100g": 5,
                "carbohydrates_100g": 20,
                "fat_100g": 2,
            },
            "categories_tags": ["en:snacks", "en:chips"],
        }

        result = service._parse_product("012345678905", product_data, raw_response)

        assert result.barcode == "012345678905"
        assert result.name == "Test Product"
        assert result.brand == "Test Brand"
        assert result.nutrition_per_100g.calories == 100
        assert result.nutrition_per_100g.protein_g == 5

    @pytest.mark.unit
    def test_parse_product_missing_fields(self, service):
        """Should handle missing fields gracefully."""
        raw_response = {"product": {}}
        product_data = {}  # Empty product

        result = service._parse_product("012345678905", product_data, raw_response)

        assert result.barcode == "012345678905"
        assert result.name == "Unknown Product"
        assert result.brand is None

    @pytest.mark.unit
    def test_parse_categories(self, service):
        """Should parse and clean category tags."""
        raw_response = {"product": {}}
        product_data = {
            "product_name": "Test",
            "categories_tags": [
                "en:plant-based-foods",
                "en:fruits-and-vegetables",
            ],
            "nutriments": {},
        }

        result = service._parse_product("012345678905", product_data, raw_response)

        assert "Plant Based Foods" in result.categories
        assert "Fruits And Vegetables" in result.categories

    @pytest.mark.unit
    def test_parse_allergens(self, service):
        """Should parse allergen tags."""
        raw_response = {"product": {}}
        product_data = {
            "product_name": "Test",
            "allergens_tags": ["en:milk", "en:gluten"],
            "nutriments": {},
        }

        result = service._parse_product("012345678905", product_data, raw_response)

        assert "Milk" in result.allergens
        assert "Gluten" in result.allergens


class TestBarcodeServiceLookup:
    """Tests for barcode lookup functionality."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lookup_returns_cached(self):
        """Should return cached product if available."""
        service = BarcodeService()
        service.db = AsyncMock()
        service.http = AsyncMock()

        # Mock cached product
        mock_row = {
            "barcode": "012345678905",
            "name": "Cached Product",
            "brand": "Test",
            "quantity": None,
            "serving_size": None,
            "serving_size_g": None,
            "categories": "[]",
            "calories_per_100g": 100,
            "protein_g_per_100g": 5,
            "carbs_g_per_100g": 20,
            "fat_g_per_100g": 2,
            "fiber_g_per_100g": 0,
            "sugar_g_per_100g": 0,
            "sodium_mg_per_100g": 0,
            "saturated_fat_g_per_100g": 0,
            "ingredients_text": None,
            "allergens": "[]",
            "image_url": None,
            "image_thumb_url": None,
            "nutriscore_grade": None,
            "nova_group": None,
            "ecoscore_grade": None,
            "cached_at": "2024-01-01",
        }

        cursor = AsyncMock()
        cursor.fetchone.return_value = mock_row
        service.db.execute.return_value = cursor

        result = await service.lookup("012345678905")

        assert result.success == True
        assert result.source == "cache"
        assert result.product.name == "Cached Product"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lookup_known_not_found(self):
        """Should return not found for known missing barcodes."""
        service = BarcodeService()
        service.db = AsyncMock()

        # Mock: not in cache
        cache_cursor = AsyncMock()
        cache_cursor.fetchone.return_value = None

        # Mock: in not_found table
        not_found_cursor = AsyncMock()
        not_found_cursor.fetchone.return_value = {"barcode": "000000000000"}

        service.db.execute.side_effect = [cache_cursor, not_found_cursor]

        result = await service.lookup("000000000000")

        assert result.success == False
        assert result.source == "not_found"
