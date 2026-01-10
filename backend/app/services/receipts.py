"""
Receipt OCR service using Google Document AI.

Scans grocery receipts and extracts line items with prices.
Matches items to existing food database for easy import.
"""

import base64
import json
import logging
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from difflib import SequenceMatcher

from app.config import get_settings
from app.models.receipts import (
    ParsedReceipt,
    ReceiptLineItem,
    ReceiptScanResponse,
    ReceiptConfirmResponse,
    ReceiptStats,
    ResolutionStatus,
    StoreType,
    ProductCodeType,
    ExtractedProductCode,
)
from app.services.supabase import get_supabase_client, TABLES

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================================================
# Product Code Extraction
# =============================================================================


class ProductCodeExtractor:
    """Extract UPC/PLU/EAN codes from receipt OCR text."""

    # Patterns for various product code formats
    PATTERNS = [
        # UPC-A: 12 digits (most common in US)
        (r"\b(\d{12})\b", ProductCodeType.UPC_A),
        # EAN-13: 13 digits (international)
        (r"\b(\d{13})\b", ProductCodeType.EAN_13),
        # UPC with spaces/dashes (some receipts format this way)
        (r"\b(\d{1,6}[-\s]\d{5,6})\b", ProductCodeType.UPC_A),
        # PLU codes: 4-5 digits, often prefixed with PLU or #
        (r"\bPLU[:\s#]*(\d{4,5})\b", ProductCodeType.PLU),
        (r"\b#(\d{4,5})\b", ProductCodeType.PLU),
        # UPC-E: 8 digits (compressed format)
        (r"\b(\d{8})\b", ProductCodeType.UPC_E),
    ]

    def extract_codes(self, text: str) -> list[ExtractedProductCode]:
        """Extract all potential product codes from OCR text."""
        if not text:
            return []

        codes = []
        seen = set()  # Avoid duplicates

        for pattern, code_type in self.PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                raw_code = match.group(1)
                normalized = self._normalize(raw_code)

                # Skip if we've already seen this code
                if normalized in seen:
                    continue

                # Validate based on code type
                if self._validate(normalized, code_type):
                    seen.add(normalized)
                    codes.append(
                        ExtractedProductCode(
                            code=normalized,
                            code_type=code_type,
                            confidence=self._calculate_confidence(normalized, code_type),
                            source_text=match.group(0),
                        )
                    )

        # Sort by confidence (highest first)
        codes.sort(key=lambda x: x.confidence, reverse=True)
        return codes

    def _normalize(self, code: str) -> str:
        """Normalize code to digits only."""
        return "".join(c for c in code if c.isdigit())

    def _validate(self, code: str, code_type: ProductCodeType) -> bool:
        """Validate product code based on type."""
        if code_type == ProductCodeType.PLU:
            # PLU codes are 4-5 digits, no checksum
            return 4 <= len(code) <= 5

        if code_type == ProductCodeType.UPC_A:
            if len(code) != 12:
                return False
            return self._validate_upc_checksum(code)

        if code_type == ProductCodeType.EAN_13:
            if len(code) != 13:
                return False
            return self._validate_ean_checksum(code)

        if code_type == ProductCodeType.UPC_E:
            # UPC-E is 8 digits, checksum validation is complex
            return len(code) == 8

        return True

    def _validate_upc_checksum(self, code: str) -> bool:
        """Validate UPC-A check digit using standard algorithm."""
        if len(code) != 12:
            return False

        try:
            digits = [int(d) for d in code]
            # Sum of odd positions * 3 + sum of even positions
            odd_sum = sum(digits[i] for i in range(0, 11, 2))
            even_sum = sum(digits[i] for i in range(1, 11, 2))
            total = odd_sum * 3 + even_sum
            check_digit = (10 - (total % 10)) % 10
            return check_digit == digits[11]
        except (ValueError, IndexError):
            return False

    def _validate_ean_checksum(self, code: str) -> bool:
        """Validate EAN-13 check digit."""
        if len(code) != 13:
            return False

        try:
            digits = [int(d) for d in code]
            # Alternating weights of 1 and 3
            total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
            check_digit = (10 - (total % 10)) % 10
            return check_digit == digits[12]
        except (ValueError, IndexError):
            return False

    def _calculate_confidence(self, code: str, code_type: ProductCodeType) -> float:
        """Calculate confidence score for extracted code."""
        # Base confidence by code type
        if code_type == ProductCodeType.UPC_A and self._validate_upc_checksum(code):
            return 0.95  # High confidence for valid UPC
        if code_type == ProductCodeType.EAN_13 and self._validate_ean_checksum(code):
            return 0.95
        if code_type == ProductCodeType.PLU:
            return 0.7  # PLU codes are less specific
        if code_type == ProductCodeType.UPC_E:
            return 0.6  # UPC-E is less common, lower confidence

        return 0.5  # Default moderate confidence


# =============================================================================
# Store Classification
# =============================================================================


class StoreClassifier:
    """Classify store type from store name."""

    PATTERNS = {
        StoreType.GROCERY: [
            "kroger",
            "safeway",
            "publix",
            "albertsons",
            "vons",
            "ralphs",
            "fry's",
            "king soopers",
            "stop & shop",
            "stop and shop",
            "giant",
            "h-e-b",
            "heb",
            "meijer",
            "wegmans",
            "aldi",
            "lidl",
            "food lion",
            "harris teeter",
            "piggly wiggly",
            "winn-dixie",
            "winn dixie",
            "shoprite",
            "acme",
            "jewel-osco",
            "jewel osco",
        ],
        StoreType.WAREHOUSE: [
            "costco",
            "sam's club",
            "sams club",
            "bj's",
            "bjs",
        ],
        StoreType.SPECIALTY: [
            "whole foods",
            "trader joe",
            "sprouts",
            "natural grocers",
            "earth fare",
            "fresh market",
            "bristol farms",
        ],
        StoreType.CONVENIENCE: [
            "7-eleven",
            "7 eleven",
            "wawa",
            "sheetz",
            "circle k",
            "am/pm",
            "ampm",
            "quick trip",
            "quiktrip",
            "casey's",
            "caseys",
        ],
        StoreType.PHARMACY: [
            "cvs",
            "walgreens",
            "rite aid",
            "rite-aid",
        ],
    }

    def classify(self, store_name: str) -> StoreType:
        """Classify store type from name."""
        if not store_name:
            return StoreType.UNKNOWN

        name_lower = store_name.lower()

        for store_type, patterns in self.PATTERNS.items():
            if any(pattern in name_lower for pattern in patterns):
                return store_type

        return StoreType.UNKNOWN


class ReceiptService:
    """Google Document AI receipt scanning service."""

    def __init__(self):
        self.client = None
        self.processor_name = None
        self._init_client()

    def _init_client(self):
        """Initialize Google Document AI client."""
        if not settings.receipt_ocr_enabled:
            logger.warning("Receipt OCR is disabled (missing Google credentials)")
            return

        try:
            from google.cloud import documentai
            from google.oauth2 import service_account

            if settings.google_credentials_json:
                creds_dict = json.loads(settings.google_credentials_json)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                self.client = documentai.DocumentProcessorServiceClient(credentials=credentials)
            else:
                # Use default credentials (for GCE or local gcloud auth)
                self.client = documentai.DocumentProcessorServiceClient()

            self.processor_name = (
                f"projects/{settings.google_project_id}"
                f"/locations/{settings.google_location}"
                f"/processors/{settings.google_processor_id}"
            )
            logger.info(f"Receipt OCR initialized with processor: {self.processor_name}")

        except ImportError:
            logger.error("google-cloud-documentai not installed")
        except Exception as e:
            logger.error(f"Failed to initialize Document AI client: {e}")

    @property
    def is_enabled(self) -> bool:
        """Check if receipt OCR is available."""
        return self.client is not None

    async def scan_receipt(
        self,
        image_bytes: bytes,
        mime_type: str,
        user_id: str,
        auto_match: bool = True,
        auto_resolve: bool = True,
    ) -> ReceiptScanResponse:
        """
        Scan a receipt image and extract line items.

        Returns parsed receipt with optional auto-matching and resolution.

        Args:
            image_bytes: Raw image data
            mime_type: Image MIME type
            user_id: User ID for RLS
            auto_match: Whether to fuzzy match items to food database
            auto_resolve: Whether to run resolution chain (barcode extraction, OFF lookup)
        """
        start_time = time.time()

        if not self.is_enabled:
            return ReceiptScanResponse(
                success=False,
                error="Receipt OCR is not configured. Set Google Document AI credentials.",
            )

        try:
            from google.cloud import documentai
            from app.services.resolution import get_resolution_service

            # Process document
            request = documentai.ProcessRequest(
                name=self.processor_name,
                raw_document=documentai.RawDocument(
                    content=image_bytes,
                    mime_type=mime_type,
                ),
            )
            result = self.client.process_document(request=request)
            document = result.document

            # Parse the document
            receipt = await self._parse_document(document, user_id)

            # Classify store type
            if receipt.store_name:
                store_classifier = StoreClassifier()
                receipt.store_type = store_classifier.classify(receipt.store_name)

            # Auto-match items to food database (existing fuzzy matching)
            items_matched = 0
            items_unmatched = 0
            if auto_match and receipt.line_items:
                for item in receipt.line_items:
                    matched = await self._match_to_food_item(item, user_id)
                    if matched:
                        items_matched += 1
                        item.resolution_status = ResolutionStatus.FUZZY_MATCHED
                        item.resolution_method = "fuzzy_match"
                    else:
                        items_unmatched += 1

            # Run resolution chain for unmatched items
            items_barcode_matched = 0
            items_needs_manual = 0
            if auto_resolve and receipt.line_items:
                resolution_service = get_resolution_service()
                receipt = await resolution_service.batch_resolve(receipt, user_id)

                # Count resolution results
                for item in receipt.line_items:
                    if item.resolution_status == ResolutionStatus.BARCODE_MATCHED:
                        items_barcode_matched += 1
                    elif item.needs_manual_entry:
                        items_needs_manual += 1

            # Save receipt to database
            receipt_id = await self._save_receipt(receipt)
            receipt.id = receipt_id

            processing_time = (time.time() - start_time) * 1000

            return ReceiptScanResponse(
                success=True,
                receipt_id=receipt_id,
                receipt=receipt,
                items_matched=items_matched,
                items_unmatched=items_unmatched,
                items_barcode_matched=items_barcode_matched,
                items_needs_manual=items_needs_manual,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"Receipt scan error: {e}")
            return ReceiptScanResponse(
                success=False,
                error=str(e),
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    async def _parse_document(self, document, user_id: str) -> ParsedReceipt:
        """Parse Document AI response into ParsedReceipt."""
        from google.cloud import documentai

        receipt = ParsedReceipt(
            user_id=user_id,
            raw_text=document.text,
            processed_at=datetime.utcnow(),
        )

        # Extract entities
        for entity in document.entities:
            entity_type = entity.type_
            value = entity.mention_text

            if entity_type == "store_name":
                receipt.store_name = value
            elif entity_type == "store_address":
                receipt.store_address = value
            elif entity_type == "transaction_date":
                receipt.purchase_date = self._parse_date(value)
            elif entity_type == "subtotal":
                receipt.subtotal = self._parse_price(value)
            elif entity_type == "tax":
                receipt.tax = self._parse_price(value)
            elif entity_type == "total":
                receipt.total = self._parse_price(value)
            elif entity_type == "payment_method":
                receipt.payment_method = value
            elif entity_type == "line_item":
                line_item = await self._parse_line_item(entity)
                if line_item:
                    receipt.line_items.append(line_item)

        # Calculate confidence
        if document.pages:
            confidences = []
            for page in document.pages:
                for block in page.blocks:
                    if hasattr(block, 'confidence'):
                        confidences.append(block.confidence)
            if confidences:
                receipt.ocr_confidence = sum(confidences) / len(confidences)

        return receipt

    async def _parse_line_item(self, entity) -> Optional[ReceiptLineItem]:
        """Parse a line item entity."""
        raw_text = entity.mention_text
        quantity = 1
        unit_price = None
        total_price = None
        parsed_name = raw_text

        # Extract nested properties
        for prop in entity.properties:
            prop_type = prop.type_
            prop_value = prop.mention_text

            if prop_type == "line_item/quantity":
                try:
                    quantity = int(float(prop_value))
                except:
                    quantity = 1
            elif prop_type == "line_item/unit_price":
                unit_price = self._parse_price(prop_value)
            elif prop_type == "line_item/total_price":
                total_price = self._parse_price(prop_value)
            elif prop_type == "line_item/description":
                parsed_name = prop_value

        if not parsed_name or parsed_name.strip() == "":
            return None

        return ReceiptLineItem(
            raw_text=raw_text,
            parsed_name=parsed_name.strip(),
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
        )

    async def _match_to_food_item(self, line_item: ReceiptLineItem, user_id: str) -> bool:
        """Try to match a line item to an existing food item."""
        client = get_supabase_client()

        # Clean up the name for matching
        search_name = self._clean_name_for_search(line_item.parsed_name or line_item.raw_text)

        if not search_name:
            return False

        # Search food items
        result = client.table(TABLES["items"]).select("id, name").or_(
            f"user_id.eq.{user_id},user_id.is.null"
        ).ilike("name", f"%{search_name}%").limit(10).execute()

        if not result.data:
            return False

        # Find best match using fuzzy matching
        best_match = None
        best_score = 0

        for item in result.data:
            score = SequenceMatcher(None, search_name.lower(), item["name"].lower()).ratio()
            if score > best_score and score > 0.5:  # Minimum 50% match
                best_score = score
                best_match = item

        if best_match:
            line_item.food_item_id = best_match["id"]
            line_item.food_item_name = best_match["name"]
            line_item.match_confidence = best_score
            line_item.is_matched = True
            return True

        return False

    def _clean_name_for_search(self, name: str) -> str:
        """Clean product name for database search."""
        # Remove common receipt abbreviations
        name = re.sub(r'\b(org|organic)\b', 'organic', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(qty|qy)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(ea|each)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(lb|lbs)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(oz|ounce)\b', '', name, flags=re.IGNORECASE)

        # Remove price-like patterns
        name = re.sub(r'\$?\d+\.?\d*', '', name)

        # Remove special characters
        name = re.sub(r'[^\w\s]', ' ', name)

        # Collapse whitespace
        name = ' '.join(name.split())

        return name.strip()

    def _parse_date(self, value: str) -> Optional[date]:
        """Parse date from various formats."""
        formats = [
            "%m/%d/%Y", "%m/%d/%y",
            "%Y-%m-%d", "%Y/%m/%d",
            "%d-%m-%Y", "%d/%m/%Y",
            "%b %d, %Y", "%B %d, %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except:
                continue
        return None

    def _parse_price(self, value: str) -> Optional[Decimal]:
        """Parse price from string."""
        if not value:
            return None
        try:
            # Remove currency symbols and whitespace
            cleaned = re.sub(r'[^\d.]', '', value)
            if cleaned:
                return Decimal(cleaned)
        except:
            pass
        return None

    async def _save_receipt(self, receipt: ParsedReceipt) -> str:
        """Save receipt to database."""
        import json
        client = get_supabase_client()

        # Insert receipt
        receipt_data = {
            "user_id": receipt.user_id,
            "store_name": receipt.store_name,
            "store_address": receipt.store_address,
            "store_type": receipt.store_type.value if receipt.store_type else "unknown",
            "purchase_date": receipt.purchase_date.isoformat() if receipt.purchase_date else None,
            "subtotal": float(receipt.subtotal) if receipt.subtotal else None,
            "tax": float(receipt.tax) if receipt.tax else None,
            "total": float(receipt.total) if receipt.total else None,
            "raw_text": receipt.raw_text,
            "processed_at": datetime.utcnow().isoformat(),
        }

        result = client.table("receipts").insert(receipt_data).execute()
        receipt_id = result.data[0]["id"]

        # Insert line items with resolution tracking
        for i, item in enumerate(receipt.line_items):
            # Serialize extracted codes as JSON
            extracted_codes_json = [
                {
                    "code": code.code,
                    "code_type": code.code_type.value,
                    "confidence": code.confidence,
                    "source_text": code.source_text,
                }
                for code in (item.extracted_codes or [])
            ]

            item_data = {
                "receipt_id": receipt_id,
                "raw_text": item.raw_text,
                "parsed_name": item.parsed_name,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price) if item.unit_price else None,
                "total_price": float(item.total_price) if item.total_price else None,
                "food_item_id": item.food_item_id,
                "match_confidence": item.match_confidence,
                # Resolution tracking fields
                "resolution_status": item.resolution_status.value if item.resolution_status else "pending",
                "resolution_method": item.resolution_method,
                "extracted_codes": json.dumps(extracted_codes_json),
                "scanned_barcode": item.scanned_barcode,
                "off_product_name": item.off_product_name,
                "off_brand": item.off_brand,
                "off_barcode": item.off_barcode,
                "needs_manual_entry": item.needs_manual_entry,
                "manual_entry_hint": item.manual_entry_hint,
            }
            client.table("receipt_line_items").insert(item_data).execute()

        return receipt_id

    async def get_receipt(self, receipt_id: str, user_id: str) -> Optional[ParsedReceipt]:
        """Get a receipt by ID."""
        client = get_supabase_client()

        result = client.table("receipts").select("*").eq("id", receipt_id).eq("user_id", user_id).single().execute()

        if not result.data:
            return None

        receipt = ParsedReceipt(**result.data)

        # Get line items
        items_result = client.table("receipt_line_items").select("*").eq("receipt_id", receipt_id).execute()

        receipt.line_items = [ReceiptLineItem(**item) for item in (items_result.data or [])]

        return receipt

    async def confirm_receipt(
        self,
        receipt_id: str,
        user_id: str,
        confirmed_items: list,
        add_to_inventory: bool = True,
        record_prices: bool = True,
        default_storage_type: str = "refrigerator",
    ) -> ReceiptConfirmResponse:
        """Confirm and import receipt items to inventory."""
        from app.services.prices import PriceService
        from app.services.expiration import get_expiration_service

        price_service = PriceService()
        expiration_service = get_expiration_service()
        client = get_supabase_client()

        items_imported = 0
        prices_recorded = 0
        inventory_updated = 0

        try:
            # Get the receipt
            receipt = await self.get_receipt(receipt_id, user_id)
            if not receipt:
                return ReceiptConfirmResponse(
                    success=False,
                    receipt_id=receipt_id,
                    error="Receipt not found",
                )

            for confirmation in confirmed_items:
                if confirmation.skip:
                    continue

                line_item = receipt.line_items[confirmation.line_item_index]

                # Get food item name for expiration calculation
                food_item_name = line_item.food_item_name or line_item.parsed_name or ""
                storage_type = confirmation.storage_type or default_storage_type

                # Record price
                if record_prices and line_item.total_price:
                    await price_service.record_price(
                        user_id=user_id,
                        food_item_id=confirmation.food_item_id,
                        price=line_item.total_price,
                        quantity_g=confirmation.quantity_g,
                        store_name=receipt.store_name,
                        receipt_id=receipt_id,
                        source="receipt",
                    )
                    prices_recorded += 1

                # Add to inventory with expiration
                if add_to_inventory and confirmation.quantity_g:
                    # Use provided expiration or auto-calculate
                    expiration_date = confirmation.expiration_date
                    if not expiration_date:
                        # Auto-calculate expiration based on food name and storage
                        expiration_date = expiration_service.suggest_expiration(
                            food_item_name=food_item_name,
                            food_item_kind="ingredient",
                            purchase_date=receipt.purchase_date,
                            storage_type=storage_type,
                        )

                    client.table(TABLES["inventory"]).insert({
                        "user_id": user_id,
                        "food_item_id": confirmation.food_item_id,
                        "quantity_g": confirmation.quantity_g,
                        "purchase_date": receipt.purchase_date.isoformat() if receipt.purchase_date else None,
                        "expiration_date": expiration_date.isoformat() if expiration_date else None,
                        "storage_type": storage_type,
                    }).execute()
                    inventory_updated += 1

                items_imported += 1

            return ReceiptConfirmResponse(
                success=True,
                receipt_id=receipt_id,
                items_imported=items_imported,
                prices_recorded=prices_recorded,
                inventory_updated=inventory_updated,
            )

        except Exception as e:
            logger.error(f"Receipt confirmation error: {e}")
            return ReceiptConfirmResponse(
                success=False,
                receipt_id=receipt_id,
                error=str(e),
            )

    async def get_receipt_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ParsedReceipt]:
        """Get user's receipt history."""
        client = get_supabase_client()

        result = (
            client.table("receipts")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        receipts = []
        for data in result.data or []:
            receipt = ParsedReceipt(**data)
            # Get line items count (don't fetch all for history list)
            items_result = client.table("receipt_line_items").select("id", count="exact").eq("receipt_id", data["id"]).execute()
            receipts.append(receipt)

        return receipts

    async def delete_receipt(self, receipt_id: str, user_id: str) -> bool:
        """Delete a receipt."""
        client = get_supabase_client()

        # Delete line items first (cascade should handle this, but be explicit)
        client.table("receipt_line_items").delete().eq("receipt_id", receipt_id).execute()

        # Delete receipt
        result = client.table("receipts").delete().eq("id", receipt_id).eq("user_id", user_id).execute()

        return bool(result.data)

    async def get_stats(self, user_id: str) -> ReceiptStats:
        """Get receipt scanning statistics."""
        client = get_supabase_client()

        # Total receipts
        receipts_result = client.table("receipts").select("id, total", count="exact").eq("user_id", user_id).execute()

        total_receipts = receipts_result.count or 0
        total_spent = Decimal("0")
        for r in receipts_result.data or []:
            if r.get("total"):
                total_spent += Decimal(str(r["total"]))

        # Items stats
        items_result = client.table("receipt_line_items").select(
            "id, food_item_id", count="exact"
        ).execute()

        total_items = items_result.count or 0
        matched_items = sum(1 for i in (items_result.data or []) if i.get("food_item_id"))

        # This month
        from datetime import datetime
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0)
        month_result = client.table("receipts").select("id", count="exact").eq("user_id", user_id).gte(
            "created_at", month_start.isoformat()
        ).execute()

        return ReceiptStats(
            total_receipts=total_receipts,
            total_items_scanned=total_items,
            total_items_matched=matched_items,
            match_rate=matched_items / total_items if total_items > 0 else 0,
            total_spent=total_spent,
            receipts_this_month=month_result.count or 0,
        )


# Singleton
_receipt_service: Optional[ReceiptService] = None


def get_receipt_service() -> ReceiptService:
    """Get receipt service singleton."""
    global _receipt_service
    if _receipt_service is None:
        _receipt_service = ReceiptService()
    return _receipt_service
