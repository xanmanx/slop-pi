# Frontend Implementation Spec: Receipt Item Resolution System

This document describes backend changes that require corresponding frontend UI updates. The backend now implements a cascading resolution system for receipt line items that couldn't be automatically matched.

---

## Overview

When a receipt is scanned, items go through a resolution chain:

```
OCR Parse -> Fuzzy Match -> Barcode Extraction -> Open Food Facts Lookup -> Manual Queue
```

Items that can't be resolved automatically are queued for manual entry. The frontend needs to:
1. Display resolution status for each item
2. Show unresolved items that need user action
3. Provide UI for manual barcode scanning
4. Provide UI for manual item entry/linking

---

## New Data Models

### ReceiptLineItem (Extended)

Each line item now includes these new fields:

```typescript
interface ReceiptLineItem {
  // Existing fields
  id?: string;
  raw_text: string;
  parsed_name?: string;
  quantity: number;
  unit_price?: number;
  total_price?: number;
  food_item_id?: string;
  food_item_name?: string;
  match_confidence?: number;
  category?: string;
  is_matched: boolean;

  // NEW: Resolution tracking
  resolution_status: ResolutionStatus;
  resolution_method?: string;  // "fuzzy_match" | "barcode_ocr" | "barcode_scan" | "manual_link" | "manual_new"

  // NEW: Extracted/scanned barcodes
  extracted_codes: ExtractedProductCode[];
  scanned_barcode?: string;

  // NEW: Open Food Facts data (when resolved via barcode)
  off_product_name?: string;
  off_brand?: string;
  off_barcode?: string;

  // NEW: Manual entry queue
  needs_manual_entry: boolean;
  manual_entry_hint?: string;  // Suggested search term for user
}

type ResolutionStatus =
  | "pending"         // Not yet processed
  | "fuzzy_matched"   // Matched via text search
  | "barcode_matched" // Matched via barcode lookup
  | "manual_entry"    // User manually resolved
  | "unresolved"      // Needs manual intervention
  | "skipped";        // User chose to skip

interface ExtractedProductCode {
  code: string;
  code_type: "upc_a" | "upc_e" | "ean_13" | "ean_8" | "plu" | "store_sku";
  confidence: number;  // 0.0 - 1.0
  source_text: string; // Original OCR text
}
```

### ParsedReceipt (Extended)

```typescript
interface ParsedReceipt {
  // Existing fields...

  // NEW: Store classification
  store_type: StoreType;
}

type StoreType =
  | "grocery"      // Kroger, Safeway, etc.
  | "warehouse"    // Costco, Sam's Club
  | "specialty"    // Whole Foods, Trader Joe's
  | "convenience"  // 7-Eleven, Wawa
  | "pharmacy"     // CVS, Walgreens
  | "unknown";
```

### ReceiptScanResponse (Extended)

```typescript
interface ReceiptScanResponse {
  success: boolean;
  receipt_id?: string;
  receipt?: ParsedReceipt;
  items_matched: number;      // Fuzzy matched count
  items_unmatched: number;    // Failed fuzzy match
  items_barcode_matched: number;  // NEW: Resolved via barcode
  items_needs_manual: number;     // NEW: Needs user action
  processing_time_ms: number;
  error?: string;
}
```

---

## New API Endpoints

### 1. Get Unresolved Items

```
GET /api/receipts/{receipt_id}/unresolved?user_id={user_id}
```

**Response:** `ResolutionStatusResponse`
```typescript
interface ResolutionStatusResponse {
  receipt_id: string;
  total_items: number;
  resolved: number;
  unresolved: number;
  resolution_rate: number;  // 0.0 - 1.0
  unresolved_items: ReceiptLineItem[];
}
```

**Use case:** After scanning, fetch unresolved items to display manual resolution UI.

---

### 2. Scan Barcode for Item

```
POST /api/receipts/{receipt_id}/items/{item_index}/scan-barcode?barcode={barcode}&user_id={user_id}
```

**Parameters:**
- `receipt_id`: Receipt UUID
- `item_index`: Zero-based index of the line item
- `barcode`: Scanned barcode string (query param)
- `user_id`: User UUID (query param)

**Response:** `ReceiptLineItem` (updated)

**Use case:** User scans physical product barcode to resolve an unmatched item.

---

### 3. Manual Resolution

```
POST /api/receipts/{receipt_id}/items/{item_index}/resolve-manual?user_id={user_id}
```

**Request Body:**
```typescript
interface ManualResolutionRequest {
  food_item_id?: string;      // Link to existing food item
  create_new?: boolean;       // Create new food item
  new_item_name?: string;     // Name for new item
  new_item_barcode?: string;  // Optional barcode for new item
  quantity_g?: number;        // Quantity in grams
  skip?: boolean;             // Skip this item entirely
}
```

**Response:** `ReceiptLineItem` (updated)

**Use cases:**
- Link to existing food item: `{ food_item_id: "uuid" }`
- Create new food item: `{ create_new: true, new_item_name: "Organic Bananas" }`
- Skip item: `{ skip: true }`

---

### 4. Retry Resolution

```
POST /api/receipts/{receipt_id}/retry-resolution?user_id={user_id}
```

**Request Body (optional):**
```typescript
{
  item_indices?: number[];  // Specific items to retry, or null for all unresolved
}
```

**Response:** `ReceiptScanResponse`

**Use case:** Retry resolution after cache updates or if user wants to re-attempt automatic matching.

---

## UI Components Needed

### 1. Resolution Status Badge

Display resolution status for each line item:

```
| Status          | Color   | Icon        | Label              |
|-----------------|---------|-------------|-------------------|
| fuzzy_matched   | Green   | Check       | "Auto-matched"     |
| barcode_matched | Blue    | Barcode     | "Barcode matched"  |
| manual_entry    | Purple  | User        | "Manual entry"     |
| unresolved      | Orange  | Warning     | "Needs attention"  |
| skipped         | Gray    | Skip        | "Skipped"          |
| pending         | Yellow  | Clock       | "Processing..."    |
```

### 2. Unresolved Items Panel

After receipt scan, show panel if `items_needs_manual > 0`:

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠️  3 items need your help                                 │
│                                                             │
│  These items couldn't be matched automatically.             │
│  You can scan the barcode or enter manually.                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ "ORG BAN 2.49"                                      │   │
│  │ Hint: "organic banana"                              │   │
│  │ Extracted codes: 4011 (PLU)                         │   │
│  │                                                     │   │
│  │ [📷 Scan Barcode] [🔍 Search Foods] [➕ Create New] [⏭️ Skip] │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ "KRGR MLK 1GL"                                      │   │
│  │ Hint: "kroger milk"                                 │   │
│  │ Extracted codes: 011110000125 (UPC-A, 95% conf)     │   │
│  │                                                     │   │
│  │ [📷 Scan Barcode] [🔍 Search Foods] [➕ Create New] [⏭️ Skip] │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3. Barcode Scanner Modal

When user taps "Scan Barcode":

```
┌─────────────────────────────────────────┐
│         Scan Product Barcode            │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │                                 │   │
│  │      [Camera Viewfinder]        │   │
│  │                                 │   │
│  └─────────────────────────────────┘   │
│                                         │
│  Point camera at barcode on product     │
│                                         │
│  Or enter manually:                     │
│  ┌─────────────────────────────────┐   │
│  │ [                             ] │   │
│  └─────────────────────────────────┘   │
│                                         │
│  [Cancel]              [Submit Barcode] │
└─────────────────────────────────────────┘
```

After successful scan, call `POST /scan-barcode` endpoint and show result.

### 4. Food Search/Link Modal

When user taps "Search Foods":

```
┌─────────────────────────────────────────┐
│         Link to Food Item               │
│                                         │
│  Search: [organic banana        ] 🔍    │
│                                         │
│  Results:                               │
│  ┌─────────────────────────────────┐   │
│  │ ○ Banana, raw                   │   │
│  │ ○ Banana, organic               │   │
│  │ ○ Banana chips                  │   │
│  └─────────────────────────────────┘   │
│                                         │
│  [Cancel]                    [Link Item]│
└─────────────────────────────────────────┘
```

Pre-populate search with `manual_entry_hint` if available.

### 5. Create New Food Modal

When user taps "Create New":

```
┌─────────────────────────────────────────┐
│         Create New Food Item            │
│                                         │
│  Name: [Organic Bananas         ]       │
│                                         │
│  Barcode (optional): [4011      ]       │
│                                         │
│  Category: [Produce          ▼]         │
│                                         │
│  [Cancel]                      [Create] │
└─────────────────────────────────────────┘
```

Pre-populate name from `parsed_name` or `manual_entry_hint`.

### 6. Receipt Scan Results Summary

Update the post-scan summary to show resolution breakdown:

```
┌─────────────────────────────────────────┐
│  ✅ Receipt Scanned Successfully        │
│                                         │
│  Store: Kroger (Grocery)                │
│  Date: Jan 10, 2026                     │
│  Total: $47.82                          │
│                                         │
│  Items: 12 total                        │
│  ├── ✅ 7 auto-matched                  │
│  ├── 📊 2 barcode-matched               │
│  └── ⚠️ 3 need attention                │
│                                         │
│  [Review Unresolved Items]              │
│  [Confirm All Matched Items]            │
└─────────────────────────────────────────┘
```

---

## User Flow

### Happy Path (All Items Resolved)

1. User scans receipt
2. Backend returns `items_needs_manual: 0`
3. Show confirmation screen with all matched items
4. User confirms → items added to inventory

### Manual Resolution Flow

1. User scans receipt
2. Backend returns `items_needs_manual: 3`
3. Show summary with "3 items need attention" alert
4. User taps "Review Unresolved Items"
5. For each unresolved item, user can:
   - **Scan Barcode**: Opens camera, scans, calls `/scan-barcode`
   - **Search Foods**: Opens search modal, user selects, calls `/resolve-manual` with `food_item_id`
   - **Create New**: Opens create modal, user fills form, calls `/resolve-manual` with `create_new: true`
   - **Skip**: Calls `/resolve-manual` with `skip: true`
6. Once all items resolved/skipped, proceed to confirmation

---

## State Management

Track resolution state for the receipt review screen:

```typescript
interface ReceiptReviewState {
  receipt: ParsedReceipt;
  resolutionSummary: {
    total: number;
    resolved: number;
    unresolved: number;
    resolutionRate: number;
  };
  unresolvedItems: ReceiptLineItem[];
  isResolving: boolean;  // Loading state during resolution
  activeItemIndex?: number;  // Currently being resolved
}
```

---

## API Integration Examples

### Scan Receipt with Resolution

```typescript
const scanReceipt = async (imageBase64: string, userId: string) => {
  const response = await fetch(`/api/receipts/scan?user_id=${userId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image_base64: imageBase64,
      mime_type: 'image/jpeg',
      auto_match: true,
      auto_resolve: true,  // NEW: Enable resolution chain
    }),
  });
  return response.json();
};
```

### Scan Barcode for Item

```typescript
const scanBarcodeForItem = async (
  receiptId: string,
  itemIndex: number,
  barcode: string,
  userId: string
) => {
  const response = await fetch(
    `/api/receipts/${receiptId}/items/${itemIndex}/scan-barcode?barcode=${barcode}&user_id=${userId}`,
    { method: 'POST' }
  );
  return response.json();
};
```

### Manual Resolution

```typescript
const resolveManually = async (
  receiptId: string,
  itemIndex: number,
  resolution: ManualResolutionRequest,
  userId: string
) => {
  const response = await fetch(
    `/api/receipts/${receiptId}/items/${itemIndex}/resolve-manual?user_id=${userId}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(resolution),
    }
  );
  return response.json();
};

// Link to existing food
await resolveManually(receiptId, 2, { food_item_id: 'uuid-123' }, userId);

// Create new food
await resolveManually(receiptId, 2, {
  create_new: true,
  new_item_name: 'Organic Bananas',
  new_item_barcode: '4011'
}, userId);

// Skip item
await resolveManually(receiptId, 2, { skip: true }, userId);
```

---

## Visual Design Recommendations

### Color Coding by Resolution Status

| Status | Background | Border | Text |
|--------|------------|--------|------|
| `fuzzy_matched` | `green-50` | `green-200` | `green-800` |
| `barcode_matched` | `blue-50` | `blue-200` | `blue-800` |
| `manual_entry` | `purple-50` | `purple-200` | `purple-800` |
| `unresolved` | `orange-50` | `orange-200` | `orange-800` |
| `skipped` | `gray-50` | `gray-200` | `gray-500` |

### Icons

- Fuzzy matched: `CheckCircle`
- Barcode matched: `Barcode` or `QrCode`
- Manual entry: `UserCheck` or `Pencil`
- Unresolved: `AlertTriangle`
- Skipped: `SkipForward`
- Scan action: `Camera` or `Scan`
- Search action: `Search`
- Create action: `Plus`

---

## Error Handling

### Barcode Not Found

When `/scan-barcode` returns but item still has `needs_manual_entry: true`:

```
"Barcode not found in database. Try searching manually or create a new item."
```

### Network Errors

Show retry option:
```
"Couldn't connect to server. [Retry] [Skip Item]"
```

---

## Testing Checklist

- [ ] Receipt scan shows resolution summary with new fields
- [ ] Unresolved items panel appears when `items_needs_manual > 0`
- [ ] Barcode scanner opens and captures barcode
- [ ] Barcode scan updates item status on success
- [ ] Food search modal pre-populates with hint
- [ ] Linking existing food updates item status
- [ ] Creating new food updates item status
- [ ] Skip updates item to `skipped` status
- [ ] Resolution progress updates in real-time
- [ ] All items resolved enables confirmation button
- [ ] Retry resolution button works for failed items
