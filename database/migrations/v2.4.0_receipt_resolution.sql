-- slop-pi v2.4.0 Migration: Receipt Resolution Fallback System
-- Adds resolution tracking, barcode extraction, and store classification
--
-- Run this in Supabase SQL Editor

-- ============================================================================
-- Add store_type to receipts table
-- ============================================================================

ALTER TABLE receipts
ADD COLUMN IF NOT EXISTS store_type TEXT DEFAULT 'unknown';

COMMENT ON COLUMN receipts.store_type IS 'Classified store type: grocery, warehouse, specialty, convenience, pharmacy, unknown';

-- ============================================================================
-- Add resolution tracking to receipt_line_items table
-- ============================================================================

-- Resolution status tracking
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS resolution_status TEXT DEFAULT 'pending';

COMMENT ON COLUMN receipt_line_items.resolution_status IS 'Resolution status: pending, fuzzy_matched, barcode_matched, manual_entry, unresolved, skipped';

-- Resolution method (how was it resolved)
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS resolution_method TEXT;

COMMENT ON COLUMN receipt_line_items.resolution_method IS 'Method used to resolve: fuzzy_match, barcode_ocr, barcode_scan, manual';

-- Extracted product codes from OCR text (JSON array)
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS extracted_codes JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN receipt_line_items.extracted_codes IS 'Product codes extracted from OCR text: [{code, code_type, confidence, source_text}]';

-- User-scanned barcode (manual fallback)
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS scanned_barcode TEXT;

COMMENT ON COLUMN receipt_line_items.scanned_barcode IS 'Barcode scanned by user as fallback resolution';

-- Open Food Facts product data
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS off_product_name TEXT;

ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS off_brand TEXT;

ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS off_barcode TEXT;

COMMENT ON COLUMN receipt_line_items.off_product_name IS 'Product name from Open Food Facts';
COMMENT ON COLUMN receipt_line_items.off_brand IS 'Brand from Open Food Facts';
COMMENT ON COLUMN receipt_line_items.off_barcode IS 'Barcode that matched in Open Food Facts';

-- Manual entry queue tracking
ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS needs_manual_entry BOOLEAN DEFAULT FALSE;

ALTER TABLE receipt_line_items
ADD COLUMN IF NOT EXISTS manual_entry_hint TEXT;

COMMENT ON COLUMN receipt_line_items.needs_manual_entry IS 'Whether item needs manual resolution';
COMMENT ON COLUMN receipt_line_items.manual_entry_hint IS 'Suggested search term for manual lookup';

-- ============================================================================
-- Indexes for efficient querying
-- ============================================================================

-- Index for querying unresolved items (partial index for performance)
CREATE INDEX IF NOT EXISTS idx_receipt_items_unresolved
    ON receipt_line_items(receipt_id, resolution_status)
    WHERE resolution_status IN ('pending', 'unresolved');

-- Index for items needing manual entry
CREATE INDEX IF NOT EXISTS idx_receipt_items_manual
    ON receipt_line_items(receipt_id)
    WHERE needs_manual_entry = TRUE;

-- Index for barcode lookups
CREATE INDEX IF NOT EXISTS idx_receipt_items_barcode
    ON receipt_line_items(scanned_barcode)
    WHERE scanned_barcode IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_receipt_items_off_barcode
    ON receipt_line_items(off_barcode)
    WHERE off_barcode IS NOT NULL;

-- Index for store type filtering
CREATE INDEX IF NOT EXISTS idx_receipts_store_type
    ON receipts(store_type);

-- ============================================================================
-- Update existing records to have proper defaults
-- ============================================================================

-- Set resolution_status based on existing match data
UPDATE receipt_line_items
SET resolution_status = CASE
    WHEN food_item_id IS NOT NULL AND match_confidence >= 0.5 THEN 'fuzzy_matched'
    WHEN food_item_id IS NOT NULL THEN 'manual_entry'
    ELSE 'pending'
END
WHERE resolution_status IS NULL OR resolution_status = 'pending';

-- Mark unmatched items as needing manual entry
UPDATE receipt_line_items
SET needs_manual_entry = TRUE
WHERE food_item_id IS NULL
AND resolution_status = 'pending';
