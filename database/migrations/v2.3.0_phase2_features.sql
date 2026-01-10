-- slop-pi v2.3.0 Migration: Phase 2 Features
-- Receipt OCR, Price Tracking, and Expiration Management
--
-- Run this in Supabase SQL Editor

-- ============================================================================
-- Receipts Table (Receipt OCR)
-- ============================================================================

CREATE TABLE IF NOT EXISTS receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    store_name TEXT,
    store_address TEXT,
    purchase_date DATE,
    subtotal DECIMAL(10,2),
    tax DECIMAL(10,2),
    total DECIMAL(10,2),
    payment_method TEXT,
    raw_text TEXT,
    image_path TEXT,
    ocr_confidence FLOAT,
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only see their own receipts
CREATE POLICY "Users can view own receipts"
    ON receipts FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own receipts"
    ON receipts FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own receipts"
    ON receipts FOR DELETE
    USING (auth.uid() = user_id);

CREATE INDEX idx_receipts_user ON receipts(user_id, purchase_date DESC);
CREATE INDEX idx_receipts_store ON receipts(store_name);

-- ============================================================================
-- Receipt Line Items Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS receipt_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id UUID REFERENCES receipts(id) ON DELETE CASCADE,
    raw_text TEXT,
    parsed_name TEXT,
    quantity INTEGER DEFAULT 1,
    unit_price DECIMAL(10,2),
    total_price DECIMAL(10,2),
    food_item_id UUID REFERENCES foodos2_food_items(id) ON DELETE SET NULL,
    match_confidence FLOAT,
    category TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Enable RLS (inherits from receipt via join)
ALTER TABLE receipt_line_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own receipt items"
    ON receipt_line_items FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM receipts r
            WHERE r.id = receipt_line_items.receipt_id
            AND r.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own receipt items"
    ON receipt_line_items FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM receipts r
            WHERE r.id = receipt_line_items.receipt_id
            AND r.user_id = auth.uid()
        )
    );

CREATE INDEX idx_receipt_items_receipt ON receipt_line_items(receipt_id);
CREATE INDEX idx_receipt_items_food ON receipt_line_items(food_item_id);

-- ============================================================================
-- Price History Table (Price Tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    food_item_id UUID REFERENCES foodos2_food_items(id) ON DELETE CASCADE,
    price DECIMAL(10,2) NOT NULL,
    price_per_100g DECIMAL(10,4),
    quantity_g DECIMAL(10,2),
    store_name TEXT,
    receipt_id UUID REFERENCES receipts(id) ON DELETE SET NULL,
    source TEXT DEFAULT 'manual', -- manual, receipt, barcode
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE price_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own prices"
    ON price_history FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own prices"
    ON price_history FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own prices"
    ON price_history FOR DELETE
    USING (auth.uid() = user_id);

CREATE INDEX idx_prices_item ON price_history(food_item_id, recorded_at DESC);
CREATE INDEX idx_prices_store ON price_history(store_name, recorded_at DESC);
CREATE INDEX idx_prices_user ON price_history(user_id, recorded_at DESC);

-- ============================================================================
-- Inventory Expiration Columns
-- ============================================================================

-- Add expiration-related columns to existing inventory table
ALTER TABLE foodos2_inventory_items
ADD COLUMN IF NOT EXISTS purchase_date DATE,
ADD COLUMN IF NOT EXISTS expiration_date DATE,
ADD COLUMN IF NOT EXISTS storage_type TEXT DEFAULT 'refrigerator';

-- Index for expiration queries
CREATE INDEX IF NOT EXISTS idx_inventory_expiration
    ON foodos2_inventory_items(user_id, expiration_date)
    WHERE expiration_date IS NOT NULL;

-- ============================================================================
-- Shelf Life Corrections Table (Learning)
-- ============================================================================

CREATE TABLE IF NOT EXISTS shelf_life_corrections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    food_item_id UUID REFERENCES foodos2_food_items(id) ON DELETE CASCADE,
    category TEXT,
    storage_type TEXT,
    expected_days INTEGER,
    actual_days INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE shelf_life_corrections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own corrections"
    ON shelf_life_corrections FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own corrections"
    ON shelf_life_corrections FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_shelf_corrections_item ON shelf_life_corrections(food_item_id);
CREATE INDEX idx_shelf_corrections_category ON shelf_life_corrections(category, storage_type);

-- ============================================================================
-- Add barcode column to food items (if not exists)
-- ============================================================================

ALTER TABLE foodos2_food_items
ADD COLUMN IF NOT EXISTS barcode TEXT,
ADD COLUMN IF NOT EXISTS brand TEXT;

CREATE INDEX IF NOT EXISTS idx_food_items_barcode
    ON foodos2_food_items(barcode)
    WHERE barcode IS NOT NULL;

-- ============================================================================
-- Service role policies (for backend access)
-- ============================================================================

-- Allow service role full access (for Pi backend)
CREATE POLICY "Service role has full access to receipts"
    ON receipts FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role has full access to receipt_line_items"
    ON receipt_line_items FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role has full access to price_history"
    ON price_history FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role has full access to shelf_life_corrections"
    ON shelf_life_corrections FOR ALL
    USING (auth.role() = 'service_role');

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE receipts IS 'Scanned grocery receipts with OCR data';
COMMENT ON TABLE receipt_line_items IS 'Individual items from scanned receipts';
COMMENT ON TABLE price_history IS 'Historical prices for food items';
COMMENT ON TABLE shelf_life_corrections IS 'User corrections to shelf life estimates for learning';

COMMENT ON COLUMN foodos2_inventory_items.purchase_date IS 'When the item was purchased';
COMMENT ON COLUMN foodos2_inventory_items.expiration_date IS 'Expected expiration date';
COMMENT ON COLUMN foodos2_inventory_items.storage_type IS 'Storage location: pantry, refrigerator, or freezer';

COMMENT ON COLUMN price_history.source IS 'How the price was recorded: manual, receipt, or barcode';
COMMENT ON COLUMN price_history.price_per_100g IS 'Normalized price per 100g for comparison';
