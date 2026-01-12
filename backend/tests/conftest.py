"""
Pytest configuration and shared fixtures.

Fixtures defined here are available to all tests.
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set test environment
os.environ["TESTING"] = "true"


# =============================================================================
# App Fixtures
# =============================================================================


@pytest.fixture
def app():
    """FastAPI test application."""
    from app.main import app
    return app


@pytest.fixture
def client(app):
    """Sync test client for API tests."""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
async def async_client(app):
    """Async test client for API tests."""
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for unit tests."""
    mock = MagicMock()
    mock.table.return_value.select.return_value.execute.return_value.data = []
    mock.table.return_value.insert.return_value.execute.return_value.data = [{"id": "test-uuid"}]
    mock.table.return_value.update.return_value.execute.return_value.data = [{}]
    mock.table.return_value.delete.return_value.execute.return_value.data = [{}]
    return mock


@pytest.fixture
def test_user_id():
    """Test user ID for database operations."""
    return "test-user-00000000-0000-0000-0000-000000000000"


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_food_item():
    """Sample food item data."""
    return {
        "id": "food-item-uuid",
        "user_id": "test-user-uuid",
        "name": "Organic Bananas",
        "kind": "ingredient",
        "serving_g": 118.0,
        "calories_per_100g": 89.0,
        "protein_g_per_100g": 1.1,
        "carbs_g_per_100g": 22.8,
        "fat_g_per_100g": 0.3,
    }


@pytest.fixture
def sample_receipt_text():
    """Sample OCR text from ALDI receipt."""
    return """ALDI
Store #119
5110 Red Arrow Hwy
Stevensville
https://help.aldi.us

382624 Grk 5% Plain Yog     7.38 FA
2 x     3.69
382260 Plain NF Greek Yog   3.19 FA
356646 Strawberries         5.69 FA
356570 Org Strawberries     3.69 FA
382931 Sour Cream           1.79 FA
356574 Org. Yellow Potato   4.39 FA
356636 White Sliced Mush    1.79 FA
356445 Org Blueberries      2.99 FA
382408 Grassfed Grnd Beef  19.47 FA
3 x     6.49
366022 Raw Honey            6.79 FA
356486 Avocados             2.45 FA
5 x     0.49
356615 Roma Tomatoes LRW    0.19 FA
445412 Italian Loaf         3.79 FA

SUBTOTAL                   63.50
T O T A L                $ 63.50
20 ITEMS
Debit Card               $ 63.50
"""


@pytest.fixture
def sample_line_item():
    """Sample receipt line item."""
    from app.models.receipts import ReceiptLineItem, ResolutionStatus
    return ReceiptLineItem(
        raw_text="356486 Avocados 2.45 FA",
        parsed_name="Avocados",
        quantity=1,
        total_price=Decimal("2.45"),
        resolution_status=ResolutionStatus.PENDING,
    )


@pytest.fixture
def sample_barcode_product():
    """Sample product from Open Food Facts."""
    return {
        "barcode": "012345678901",
        "name": "Organic Apple Juice",
        "brand": "Simply Orange",
        "categories": ["Beverages", "Juices"],
        "nutrition_per_100g": {
            "calories": 46,
            "protein_g": 0.1,
            "carbs_g": 11.0,
            "fat_g": 0.1,
        }
    }


# =============================================================================
# Mock Service Fixtures
# =============================================================================


@pytest.fixture
def mock_barcode_service():
    """Mock barcode service."""
    mock = AsyncMock()
    mock.lookup.return_value.success = True
    mock.lookup.return_value.product = MagicMock(
        name="Test Product",
        brand="Test Brand",
        barcode="012345678901"
    )
    return mock


@pytest.fixture
def mock_ocr():
    """Mock OCR function."""
    def _mock_ocr(image_bytes):
        return "ALDI\nStore #119\n356486 Avocados 2.45 FA\nTOTAL $2.45"
    return _mock_ocr


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def temp_image(tmp_path):
    """Create a temporary test image."""
    from PIL import Image
    import io

    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='white')
    img_path = tmp_path / "test_receipt.jpg"
    img.save(img_path)

    return img_path


@pytest.fixture
def image_bytes(temp_image):
    """Get image as bytes."""
    return temp_image.read_bytes()
