-- Migration: v2.5.0_grocery_lists.sql
-- Description: Add persistent grocery lists feature
-- Date: 2026-01-24

-- ============================================================================
-- Table: grocery_lists
-- Stores user's saved grocery lists with generation config
-- ============================================================================

CREATE TABLE IF NOT EXISTS grocery_lists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Identification
    name TEXT DEFAULT 'Shopping List',

    -- Date range used to generate
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- Generation config (for regeneration)
    include_meals BOOLEAN DEFAULT true,
    include_reorders BOOLEAN DEFAULT true,
    include_supplements BOOLEAN DEFAULT true,
    subtract_inventory BOOLEAN DEFAULT true,
    include_household BOOLEAN DEFAULT false,

    -- Status: active, completed, archived
    status TEXT DEFAULT 'active',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- RLS for grocery_lists
ALTER TABLE grocery_lists ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own lists" ON grocery_lists
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Service role full access grocery_lists" ON grocery_lists
    FOR ALL TO service_role USING (true);

-- Indexes for grocery_lists
CREATE INDEX IF NOT EXISTS idx_grocery_lists_user ON grocery_lists(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_grocery_lists_active ON grocery_lists(user_id, status) WHERE status = 'active';


-- ============================================================================
-- Table: grocery_list_items
-- Stores individual items in a grocery list
-- ============================================================================

CREATE TABLE IF NOT EXISTS grocery_list_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grocery_list_id UUID REFERENCES grocery_lists(id) ON DELETE CASCADE,

    -- Item reference
    food_item_id UUID REFERENCES foodos2_food_items(id) ON DELETE SET NULL,
    name TEXT NOT NULL,  -- Denormalized for display

    -- Amounts (grams)
    needed_g DECIMAL(10,2) DEFAULT 0,
    in_stock_g DECIMAL(10,2) DEFAULT 0,
    to_buy_g DECIMAL(10,2) DEFAULT 0,

    -- Sources
    from_meals DECIMAL(10,2) DEFAULT 0,
    from_reorders DECIMAL(10,2) DEFAULT 0,
    from_supplements DECIMAL(10,2) DEFAULT 0,

    -- Organization
    category TEXT DEFAULT 'other',
    sort_order INTEGER DEFAULT 0,

    -- Status
    checked BOOLEAN DEFAULT false,
    checked_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS for grocery_list_items (via parent)
ALTER TABLE grocery_list_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own list items" ON grocery_list_items
    FOR ALL USING (
        grocery_list_id IN (SELECT id FROM grocery_lists WHERE user_id = auth.uid())
    );

CREATE POLICY "Service role full access grocery_list_items" ON grocery_list_items
    FOR ALL TO service_role USING (true);

-- Indexes for grocery_list_items
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_list ON grocery_list_items(grocery_list_id);
CREATE INDEX IF NOT EXISTS idx_grocery_list_items_checked ON grocery_list_items(grocery_list_id, checked);


-- ============================================================================
-- Function: Update updated_at timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_grocery_list_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER grocery_lists_updated_at
    BEFORE UPDATE ON grocery_lists
    FOR EACH ROW
    EXECUTE FUNCTION update_grocery_list_updated_at();
