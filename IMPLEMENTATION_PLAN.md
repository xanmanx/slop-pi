# Slop-Pi Feature Implementation Plan

## Executive Summary

Based on the deep dive analysis, slop-pi has a solid foundation with comprehensive nutrition tracking, recipe DAG system, USDA integration, and meal planning. This plan outlines the implementation of **7 major features** from the ARCHITECTURE.md reference that are currently missing.

---

## Current State vs. Target State

| Feature | Current | Target | Priority |
|---------|---------|--------|----------|
| Receipt OCR | ❌ None | Google Document AI | P1 |
| Barcode Lookup | ❌ None | Open Food Facts | P1 |
| Price Tracking | ⚠️ Model only | Full history + trends | P2 |
| Inventory Prediction | ❌ None | ML consumption forecasting | P2 |
| Expiration Dates | ❌ None | Category-based + learning | P2 |
| Drinks/Caffeine | ⚠️ Via AI lookup | Dedicated tracking | P3 |
| MCP Integration | ❌ None | Full MCP server | P3 |

---

## Environment Management: Doppler

All environment variables are managed through **Doppler** for seamless sync across:
- Local development (Mac)
- Raspberry Pi deployment
- Docker containers
- CI/CD pipelines

### Doppler Project Structure
```
Project: slop-pi
├── dev          # Local development
├── staging      # Testing on Pi
└── prod         # Production on Pi
```

### Running with Doppler
```bash
# Local development
doppler run -- uvicorn backend.app.main:app --reload

# Docker
doppler run -- docker compose up

# Systemd (Pi)
# Service file uses: doppler run -- ...

# One-time setup
doppler setup  # Select project and config
```

### Doppler Secrets (Full List)

```bash
# ============================================
# EXISTING SECRETS (already configured)
# ============================================

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# USDA FoodData Central
USDA_API_KEY=your-usda-api-key

# OpenAI
OPENAI_API_KEY=sk-...

# Notifications
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=slop-notifications

# Security
PI_API_KEY=your-random-secret
CRON_SECRET=your-cron-secret

# Application
ENVIRONMENT=production
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=info

# Data Paths
DATA_DIR=/app/data
USDA_CACHE_DB=/app/data/usda_cache.db

# ============================================
# NEW SECRETS (to add for new features)
# ============================================

# Google Document AI (Receipt OCR)
GOOGLE_PROJECT_ID=your-gcp-project
GOOGLE_LOCATION=us
GOOGLE_PROCESSOR_ID=expense-parser-processor-id
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}  # Base64 or raw JSON

# Feature Flags
FEATURE_RECEIPT_OCR=true
FEATURE_BARCODE_LOOKUP=true
FEATURE_PRICE_TRACKING=true
FEATURE_PREDICTIONS=true
FEATURE_DRINKS_TRACKING=true
FEATURE_MCP_SERVER=true

# Caffeine Tracking
DAILY_CAFFEINE_LIMIT_MG=400
CAFFEINE_WARNING_THRESHOLD_MG=300

# Prediction Settings
PREDICTION_LOOKBACK_DAYS=30
PREDICTION_MIN_DATA_POINTS=7

# MCP Server
MCP_SERVER_PORT=8001
MCP_SERVER_ENABLED=true
```

### Doppler CLI Commands
```bash
# Add new secret
doppler secrets set GOOGLE_PROJECT_ID your-project-id

# Add JSON secret (for Google credentials)
doppler secrets set GOOGLE_CREDENTIALS_JSON --raw < service-account.json

# Sync to Pi
doppler configs secrets download --no-file --format env > .env.pi
scp .env.pi pi@slop.local:~/slop-pi/.env

# View all secrets
doppler secrets

# Run with specific config
doppler run -c prod -- uvicorn backend.app.main:app
```

---

## Phase 1: Quick Wins (Week 1)

### 1.1 Barcode Lookup - Open Food Facts

**Effort:** Low (1-2 days)
**Value:** High (instant product info)

**New Files:**
```
backend/app/
├── api/barcode.py          # API endpoints
├── services/barcode.py     # Open Food Facts integration
└── models/barcode.py       # Request/response models
```

**Endpoints:**
```python
GET  /api/barcode/{barcode}           # Lookup single barcode
POST /api/barcode/batch               # Lookup multiple barcodes
POST /api/barcode/import/{barcode}    # Import to food items
```

**Service Design:**
```python
class BarcodeService:
    """Open Food Facts barcode lookup with local caching."""

    BASE_URL = "https://world.openfoodfacts.org/api/v2"

    async def lookup(self, barcode: str) -> ProductInfo | None:
        """Look up product by barcode (UPC/EAN)."""
        # 1. Check SQLite cache first
        # 2. Hit Open Food Facts API
        # 3. Cache result
        # 4. Return normalized ProductInfo

    async def import_to_supabase(self, barcode: str, user_id: str) -> FoodItem:
        """Import barcode product as food item."""
```

**Model:**
```python
class ProductInfo(BaseModel):
    barcode: str
    name: str
    brand: str | None
    quantity: str | None  # "500g", "1L"
    categories: list[str]
    nutrition_per_100g: NutritionPer100g
    ingredients_text: str | None
    allergens: list[str]
    image_url: str | None
    source: Literal["cache", "api"]
```

**SQLite Cache Schema:**
```sql
CREATE TABLE barcode_cache (
    barcode TEXT PRIMARY KEY,
    product_name TEXT,
    brand TEXT,
    nutrition_json TEXT,
    raw_response TEXT,
    cached_at TIMESTAMP,
    last_accessed TIMESTAMP
);
CREATE INDEX idx_barcode_name ON barcode_cache(product_name);
```

---

### 1.2 Complete Daily Summary Cron

**Effort:** Low (2-4 hours)
**Value:** Medium (user engagement)

The endpoint exists but returns "not implemented". Just needs:

```python
# api/cron.py - complete the implementation
@router.get("/daily-summary")
async def trigger_daily_summary():
    """Send daily nutrition summary to all users."""
    users = await get_all_users_with_notifications()

    for user in users:
        stats = await get_daily_nutrition_stats(user.id)
        await notifications.send_daily_summary(
            calories=stats.nutrition.macros.calories,
            protein=stats.nutrition.macros.protein_g,
            meals_logged=stats.meals_logged,
            vitamin_score=stats.vitamin_score,
            mineral_score=stats.mineral_score
        )

    return {"success": True, "users_notified": len(users)}
```

---

## Phase 2: Core Features (Weeks 2-3)

### 2.1 Receipt OCR - Google Document AI

**Effort:** Medium (3-5 days)
**Value:** Very High (automated tracking)

**Doppler Secrets Required:**
```bash
doppler secrets set GOOGLE_PROJECT_ID your-gcp-project
doppler secrets set GOOGLE_LOCATION us
doppler secrets set GOOGLE_PROCESSOR_ID expense-parser-id
doppler secrets set GOOGLE_CREDENTIALS_JSON --raw < service-account.json
doppler secrets set FEATURE_RECEIPT_OCR true
```

**New Files:**
```
backend/app/
├── api/receipts.py           # API endpoints
├── services/receipts.py      # Document AI integration
├── services/receipt_parser.py # Receipt parsing logic
└── models/receipts.py        # Request/response models
```

**Config Integration:**
```python
# config.py additions
class Settings(BaseSettings):
    # Google Document AI
    google_project_id: str | None = None
    google_location: str = "us"
    google_processor_id: str | None = None
    google_credentials_json: str | None = None  # JSON string from Doppler

    # Feature Flags
    feature_receipt_ocr: bool = False
    feature_barcode_lookup: bool = True
    feature_price_tracking: bool = True

    @property
    def receipt_ocr_enabled(self) -> bool:
        return (
            self.feature_receipt_ocr
            and self.google_project_id
            and self.google_processor_id
        )
```

**Endpoints:**
```python
POST /api/receipts/scan           # Upload and scan receipt
GET  /api/receipts/{receipt_id}   # Get parsed receipt
POST /api/receipts/{receipt_id}/confirm  # Confirm and import items
GET  /api/receipts/history        # User's receipt history
DELETE /api/receipts/{receipt_id} # Delete receipt
```

**Service Design:**
```python
from google.cloud import documentai
from google.oauth2 import service_account
import json

class ReceiptService:
    """Google Document AI receipt scanning."""

    def __init__(self, settings: Settings):
        if settings.google_credentials_json:
            creds_dict = json.loads(settings.google_credentials_json)
            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            self.client = documentai.DocumentProcessorServiceClient(credentials=credentials)
        else:
            self.client = documentai.DocumentProcessorServiceClient()

        self.processor_name = (
            f"projects/{settings.google_project_id}"
            f"/locations/{settings.google_location}"
            f"/processors/{settings.google_processor_id}"
        )

    async def scan_receipt(self, image_bytes: bytes, mime_type: str) -> ParsedReceipt:
        """Scan receipt image and extract line items."""
        request = documentai.ProcessRequest(
            name=self.processor_name,
            raw_document=documentai.RawDocument(content=image_bytes, mime_type=mime_type),
        )
        result = self.client.process_document(request=request)
        return self._parse_document(result.document)
```

**Database Tables:**
```sql
-- Receipt storage
CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    store_name TEXT,
    store_address TEXT,
    purchase_date DATE,
    subtotal DECIMAL(10,2),
    tax DECIMAL(10,2),
    total DECIMAL(10,2),
    raw_text TEXT,
    image_path TEXT,
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Receipt line items
CREATE TABLE receipt_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id UUID REFERENCES receipts(id) ON DELETE CASCADE,
    raw_text TEXT,
    quantity INTEGER,
    unit_price DECIMAL(10,2),
    total_price DECIMAL(10,2),
    food_item_id UUID REFERENCES foodos2_food_items(id),
    match_confidence FLOAT,
    category TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_receipts_user ON receipts(user_id, purchase_date DESC);
CREATE INDEX idx_receipt_items_food ON receipt_line_items(food_item_id);
```

---

### 2.2 Price Tracking

**Effort:** Medium (2-3 days)
**Value:** High (budget awareness)

**New Files:**
```
backend/app/
├── api/prices.py           # API endpoints
├── services/prices.py      # Price analytics
└── models/prices.py        # Request/response models
```

**Endpoints:**
```python
GET  /api/prices/{food_item_id}           # Price history for item
GET  /api/prices/{food_item_id}/trend     # Price trend analysis
GET  /api/prices/compare                  # Compare prices across stores
POST /api/prices/record                   # Manual price entry
GET  /api/prices/alerts                   # Price drop alerts
```

**Service Design:**
```python
from scipy import stats

class PriceService:
    """Price tracking and analysis."""

    async def analyze_trend(
        self,
        food_item_id: str,
        days: int = 30
    ) -> PriceTrend:
        """Analyze price trend using linear regression."""
        history = await self.get_price_history(food_item_id, days)
        if len(history) < 2:
            return PriceTrend(trend_direction="stable", trend_percent=0)

        x = list(range(len(history)))
        y = [p.price for p in history]
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        trend_percent = (slope * len(history)) / y[0] * 100 if y[0] > 0 else 0
        direction = "up" if slope > 0.01 else "down" if slope < -0.01 else "stable"

        return PriceTrend(
            trend_direction=direction,
            trend_percent=round(trend_percent, 1),
            confidence=abs(r_value)
        )
```

**Database Table:**
```sql
CREATE TABLE price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    food_item_id UUID REFERENCES foodos2_food_items(id),
    price DECIMAL(10,2) NOT NULL,
    price_per_100g DECIMAL(10,4),
    quantity_g DECIMAL(10,2),
    store_name TEXT,
    receipt_id UUID REFERENCES receipts(id),
    source TEXT DEFAULT 'manual',
    recorded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_prices_item ON price_history(food_item_id, recorded_at DESC);
CREATE INDEX idx_prices_store ON price_history(store_name, recorded_at DESC);
```

---

### 2.3 Expiration Date Management

**Effort:** Medium (2-3 days)
**Value:** High (reduce food waste)

**New Files:**
```
backend/app/
├── api/expiration.py           # API endpoints
├── services/expiration.py      # Expiration logic
├── data/shelf_life.json        # Default shelf life data
└── models/expiration.py        # Request/response models
```

**Endpoints:**
```python
GET  /api/expiration/inventory          # Items sorted by expiration
GET  /api/expiration/expiring-soon      # Items expiring in N days
POST /api/expiration/set/{inventory_id} # Set/update expiration
POST /api/expiration/learned            # Record user correction
GET  /api/expiration/defaults/{category} # Get category defaults
```

**Shelf Life Data (from USDA FoodKeeper):**
```json
{
  "categories": {
    "dairy": {
      "milk": {"refrigerator_days": 7, "freezer_days": 90},
      "cheese_hard": {"refrigerator_days": 42, "freezer_days": 180},
      "yogurt": {"refrigerator_days": 14, "freezer_days": 60},
      "eggs": {"refrigerator_days": 35, "freezer_days": 365}
    },
    "meat": {
      "chicken_raw": {"refrigerator_days": 2, "freezer_days": 270},
      "beef_raw": {"refrigerator_days": 5, "freezer_days": 365},
      "ground_meat": {"refrigerator_days": 2, "freezer_days": 120}
    },
    "produce": {
      "leafy_greens": {"refrigerator_days": 7},
      "berries": {"refrigerator_days": 5, "freezer_days": 365},
      "apples": {"refrigerator_days": 28}
    }
  }
}
```

**Database Changes:**
```sql
-- Add to existing inventory table
ALTER TABLE foodos2_inventory_items
ADD COLUMN purchase_date DATE,
ADD COLUMN expiration_date DATE,
ADD COLUMN storage_type TEXT DEFAULT 'refrigerator';

-- User shelf life corrections (for learning)
CREATE TABLE shelf_life_corrections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    food_item_id UUID REFERENCES foodos2_food_items(id),
    category TEXT,
    expected_days INTEGER,
    actual_days INTEGER,
    storage_type TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Phase 3: Advanced Features (Weeks 4-5)

### 3.1 Inventory Prediction (ML)

**Effort:** High (5-7 days)
**Value:** Very High (proactive shopping)

**Doppler Secrets:**
```bash
doppler secrets set FEATURE_PREDICTIONS true
doppler secrets set PREDICTION_LOOKBACK_DAYS 30
doppler secrets set PREDICTION_MIN_DATA_POINTS 7
```

**New Files:**
```
backend/app/
├── api/predictions.py           # API endpoints
├── services/predictions.py      # Prediction engine
└── models/predictions.py        # Request/response models
```

**Endpoints:**
```python
GET  /api/predictions/depletion/{item_id}     # When will item run out
GET  /api/predictions/shopping-date           # Optimal shopping date
GET  /api/predictions/weekly-needs            # Predicted weekly needs
POST /api/predictions/train                   # Trigger model update
```

**Service Design:**
```python
from sklearn.linear_model import LinearRegression
import numpy as np

class PredictionService:
    """Inventory depletion prediction using ML."""

    async def predict_depletion(
        self,
        user_id: str,
        inventory_item_id: str
    ) -> DepletionPrediction:
        """Predict when item will run out."""
        # 1. Get consumption history
        consumption = await self._get_consumption_history(user_id, inventory_item_id)

        if len(consumption) < self.settings.prediction_min_data_points:
            return self._fallback_prediction(inventory_item_id)

        # 2. Calculate rolling average
        daily_rates = self._calculate_daily_rates(consumption)

        # 3. Apply linear regression for trend
        X = np.arange(len(daily_rates)).reshape(-1, 1)
        y = np.array(daily_rates)
        model = LinearRegression()
        model.fit(X, y)

        # 4. Predict depletion
        current_qty = await self._get_current_quantity(inventory_item_id)
        predicted_rate = model.predict([[len(daily_rates)]])[0]
        days_until_empty = current_qty / predicted_rate if predicted_rate > 0 else 999

        return DepletionPrediction(
            inventory_item_id=inventory_item_id,
            current_quantity_g=current_qty,
            daily_consumption_g=predicted_rate,
            days_until_empty=days_until_empty,
            predicted_empty_date=date.today() + timedelta(days=int(days_until_empty)),
            confidence=model.score(X, y)
        )
```

---

### 3.2 Drinks & Caffeine Tracking

**Effort:** Medium (2-3 days)
**Value:** Medium (health tracking)

**Doppler Secrets:**
```bash
doppler secrets set FEATURE_DRINKS_TRACKING true
doppler secrets set DAILY_CAFFEINE_LIMIT_MG 400
doppler secrets set CAFFEINE_WARNING_THRESHOLD_MG 300
```

**New Files:**
```
backend/app/
├── api/drinks.py           # API endpoints
├── services/drinks.py      # Drink tracking logic
├── data/caffeine_db.json   # Default caffeine values
└── models/drinks.py        # Request/response models
```

**Endpoints:**
```python
POST /api/drinks/log                    # Log a drink
GET  /api/drinks/today                  # Today's drinks
GET  /api/drinks/caffeine/today         # Today's caffeine total
GET  /api/drinks/caffeine/weekly        # Weekly caffeine trend
GET  /api/drinks/hydration              # Hydration tracking
```

**Database Table:**
```sql
CREATE TABLE drink_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    drink_type TEXT NOT NULL,
    drink_name TEXT,
    amount_ml DECIMAL(10,2) NOT NULL,
    caffeine_mg DECIMAL(10,2),
    is_water BOOLEAN DEFAULT FALSE,
    logged_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_drinks_user_date ON drink_logs(user_id, logged_at DESC);
```

---

### 3.3 MCP Server Integration

**Effort:** High (5-7 days)
**Value:** High (AI assistant integration)

**Doppler Secrets:**
```bash
doppler secrets set FEATURE_MCP_SERVER true
doppler secrets set MCP_SERVER_PORT 8001
```

**New Files:**
```
backend/app/
├── mcp/
│   ├── __init__.py
│   ├── server.py           # MCP server implementation
│   ├── tools.py            # Tool definitions
│   └── resources.py        # Resource definitions
```

**MCP Tools:**
```python
TOOLS = [
    {"name": "search_food", "description": "Search for food items by name"},
    {"name": "get_nutrition", "description": "Get nutrition info for a food item"},
    {"name": "log_meal", "description": "Log a meal to the plan"},
    {"name": "get_daily_summary", "description": "Get today's nutrition summary"},
    {"name": "scan_barcode", "description": "Look up product by barcode"},
    {"name": "get_inventory", "description": "Get current inventory status"},
    {"name": "add_to_grocery_list", "description": "Add item to grocery list"},
    {"name": "check_expiring", "description": "Check items expiring soon"},
    {"name": "get_caffeine_status", "description": "Get today's caffeine intake"},
]
```

---

## Deployment Updates

### Systemd Service with Doppler
```ini
# /etc/systemd/system/slop-pi.service
[Unit]
Description=slop-pi Meal Planning API
After=network.target

[Service]
Type=exec
User=pi
WorkingDirectory=/home/pi/slop-pi
ExecStart=/usr/local/bin/doppler run -c prod -- /home/pi/slop-pi/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

### Docker with Doppler
```yaml
# docker-compose.yml
services:
  api:
    image: slop-api
    command: >
      sh -c "doppler run -c prod -- uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"
    volumes:
      - ./data:/app/data
    environment:
      - DOPPLER_TOKEN=${DOPPLER_TOKEN}  # Service token for Docker
```

### Doppler Service Token for Pi
```bash
# Generate service token for Pi deployment
doppler configs tokens create prod --name pi-deployment

# On Pi, set token
echo "DOPPLER_TOKEN=dp.st.xxx" >> ~/.bashrc

# Verify
doppler run -- echo "Doppler connected!"
```

---

## Dependencies to Add

```txt
# requirements.txt additions

# Receipt OCR
google-cloud-documentai>=2.20.0

# ML Predictions
scikit-learn>=1.3.0

# MCP
mcp>=0.1.0

# Already have: httpx, scipy, pandas, numpy
```

---

## Database Migration Summary

```sql
-- All migrations in one file: database/migrations/v2.2.0_new_features.sql

-- Barcode cache (SQLite, local)
-- Receipt storage
-- Price history
-- Inventory expiration columns
-- Shelf life corrections
-- Drink logs
```

---

## Estimated Timeline

| Phase | Features | Duration |
|-------|----------|----------|
| Phase 1 | Barcode + Daily Summary | 3-4 days |
| Phase 2 | Receipt OCR + Prices + Expiration | 8-10 days |
| Phase 3 | Predictions + Drinks + MCP | 10-14 days |
| Phase 4 | Polish + Tests + Docs | 5-7 days |
| **Total** | All features | **~5-6 weeks** |

---

## Quick Start Commands

```bash
# 1. Add new Doppler secrets
doppler secrets set FEATURE_BARCODE_LOOKUP true
doppler secrets set FEATURE_RECEIPT_OCR true
doppler secrets set GOOGLE_PROJECT_ID your-project
# ... etc

# 2. Install new dependencies
cd /Users/xande/dev/slop-pi
uv add google-cloud-documentai scikit-learn mcp

# 3. Run migrations (Supabase SQL editor)
# Paste contents of database/migrations/v2.2.0_new_features.sql

# 4. Test locally
doppler run -- uvicorn backend.app.main:app --reload

# 5. Deploy to Pi
ssh pi@slop.local
cd slop-pi && git pull
sudo systemctl restart slop-pi
```

---

*Last Updated: 2026-01-08*
*Environment Management: Doppler*
