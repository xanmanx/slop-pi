"""
Resolution service for receipt line items.

Implements a fallback chain for resolving receipt items:
1. Fuzzy match (already done by ReceiptService)
2. Barcode extraction from OCR text
3. Open Food Facts lookup
4. Queue for manual entry
"""

import asyncio
import logging
import re
from typing import Optional

from app.models.receipts import (
    ParsedReceipt,
    ReceiptLineItem,
    ResolutionStatus,
    ExtractedProductCode,
)
from app.services.receipts import ProductCodeExtractor, StoreClassifier

logger = logging.getLogger(__name__)


class ResolutionService:
    """Handles fallback chain for resolving receipt line items."""

    def __init__(self):
        self.code_extractor = ProductCodeExtractor()
        self.store_classifier = StoreClassifier()
        self._barcode_service = None  # Lazy init

    async def _get_barcode_service(self):
        """Lazy-load barcode service to avoid circular imports."""
        if self._barcode_service is None:
            from app.services.barcode import get_barcode_service

            self._barcode_service = await get_barcode_service()
        return self._barcode_service

    async def resolve_line_item(
        self,
        line_item: ReceiptLineItem,
        user_id: str,
    ) -> ReceiptLineItem:
        """
        Attempt to resolve a line item through the fallback chain.

        Chain:
        1. Check if already fuzzy matched (skip if so)
        2. Extract barcodes from OCR text
        3. Look up in Open Food Facts
        4. Queue for manual entry if all else fails
        """
        # Already matched by existing fuzzy logic?
        if line_item.is_matched and (line_item.match_confidence or 0) >= 0.5:
            line_item.resolution_status = ResolutionStatus.FUZZY_MATCHED
            line_item.resolution_method = "fuzzy_match"
            return line_item

        # Step 1: Extract barcodes from raw OCR text
        text_to_search = f"{line_item.raw_text} {line_item.parsed_name or ''}"
        extracted_codes = self.code_extractor.extract_codes(text_to_search)
        line_item.extracted_codes = extracted_codes

        if extracted_codes:
            logger.debug(
                f"Extracted {len(extracted_codes)} codes from '{line_item.parsed_name}': "
                f"{[c.code for c in extracted_codes]}"
            )

            # Step 2: Try Open Food Facts lookup for each extracted code
            barcode_service = await self._get_barcode_service()

            for code in extracted_codes:
                try:
                    result = await barcode_service.lookup(code.code)

                    if result.success and result.product:
                        # Match found!
                        line_item.resolution_status = ResolutionStatus.BARCODE_MATCHED
                        line_item.resolution_method = "barcode_ocr"
                        line_item.off_barcode = code.code
                        line_item.off_product_name = result.product.name
                        line_item.off_brand = result.product.brand
                        line_item.food_item_name = result.product.name
                        line_item.is_matched = True
                        line_item.match_confidence = code.confidence
                        line_item.needs_manual_entry = False

                        logger.info(
                            f"Resolved '{line_item.parsed_name}' via barcode {code.code} "
                            f"-> {result.product.name}"
                        )
                        return line_item

                except Exception as e:
                    logger.warning(f"OFF lookup error for {code.code}: {e}")
                    continue

        # Step 3: Queue for manual entry
        await self._queue_for_manual_entry(line_item)
        return line_item

    async def _queue_for_manual_entry(self, line_item: ReceiptLineItem) -> None:
        """Mark item as needing manual entry with helpful context."""
        line_item.resolution_status = ResolutionStatus.UNRESOLVED
        line_item.needs_manual_entry = True
        line_item.manual_entry_hint = self._generate_hint(
            line_item.parsed_name or line_item.raw_text
        )

        logger.debug(
            f"Queued for manual entry: '{line_item.parsed_name}' "
            f"(hint: {line_item.manual_entry_hint})"
        )

    def _generate_hint(self, name: str) -> str:
        """Generate a search hint for manual lookup."""
        if not name:
            return ""

        # Clean up the name for search
        hint = name.lower()

        # Remove common receipt abbreviations
        hint = re.sub(r"\b(org|organic)\b", "organic", hint, flags=re.IGNORECASE)
        hint = re.sub(r"\b(qty|qy)\b", "", hint, flags=re.IGNORECASE)
        hint = re.sub(r"\b(ea|each)\b", "", hint, flags=re.IGNORECASE)
        hint = re.sub(r"\b(lb|lbs)\b", "", hint, flags=re.IGNORECASE)
        hint = re.sub(r"\b(oz|ounce)\b", "", hint, flags=re.IGNORECASE)

        # Remove price patterns
        hint = re.sub(r"\$?\d+\.?\d*", "", hint)

        # Remove special characters
        hint = re.sub(r"[^\w\s]", " ", hint)

        # Collapse whitespace
        hint = " ".join(hint.split())

        return hint.strip()

    async def resolve_with_scanned_barcode(
        self,
        line_item: ReceiptLineItem,
        barcode: str,
    ) -> ReceiptLineItem:
        """
        Resolve a line item using a manually scanned barcode.

        This is the fallback when automatic extraction fails but the user
        can scan the physical product.
        """
        barcode_service = await self._get_barcode_service()

        # Normalize barcode
        barcode = "".join(c for c in barcode if c.isdigit())
        line_item.scanned_barcode = barcode

        try:
            result = await barcode_service.lookup(barcode)

            if result.success and result.product:
                line_item.resolution_status = ResolutionStatus.BARCODE_MATCHED
                line_item.resolution_method = "barcode_scan"
                line_item.off_barcode = barcode
                line_item.off_product_name = result.product.name
                line_item.off_brand = result.product.brand
                line_item.food_item_name = result.product.name
                line_item.is_matched = True
                line_item.match_confidence = 0.95  # High confidence for scanned barcode
                line_item.needs_manual_entry = False

                logger.info(
                    f"Resolved via scanned barcode {barcode} -> {result.product.name}"
                )
                return line_item

        except Exception as e:
            logger.warning(f"OFF lookup error for scanned barcode {barcode}: {e}")

        # Barcode not found in OFF, still needs manual entry
        logger.info(f"Scanned barcode {barcode} not found in Open Food Facts")
        return line_item

    async def batch_resolve(
        self,
        receipt: ParsedReceipt,
        user_id: str,
    ) -> ParsedReceipt:
        """Resolve all unresolved items in a receipt in parallel."""
        if not receipt.line_items:
            return receipt

        # Classify store type
        if receipt.store_name:
            receipt.store_type = self.store_classifier.classify(receipt.store_name)

        # Create tasks for all items that need resolution
        tasks = []
        for item in receipt.line_items:
            # Only resolve items that aren't already matched
            if not item.is_matched or item.resolution_status == ResolutionStatus.PENDING:
                tasks.append(self.resolve_line_item(item, user_id))
            else:
                # Already matched, just mark the status
                item.resolution_status = ResolutionStatus.FUZZY_MATCHED
                item.resolution_method = "fuzzy_match"

        # Run resolution in parallel
        if tasks:
            await asyncio.gather(*tasks)

        return receipt

    def get_resolution_summary(self, receipt: ParsedReceipt) -> dict:
        """Get summary statistics for resolution status."""
        if not receipt.line_items:
            return {
                "total_items": 0,
                "fuzzy_matched": 0,
                "barcode_matched": 0,
                "manual_entry": 0,
                "unresolved": 0,
                "skipped": 0,
                "resolution_rate": 0.0,
            }

        counts = {
            ResolutionStatus.FUZZY_MATCHED: 0,
            ResolutionStatus.BARCODE_MATCHED: 0,
            ResolutionStatus.MANUAL_ENTRY: 0,
            ResolutionStatus.UNRESOLVED: 0,
            ResolutionStatus.SKIPPED: 0,
            ResolutionStatus.PENDING: 0,
        }

        for item in receipt.line_items:
            counts[item.resolution_status] = counts.get(item.resolution_status, 0) + 1

        total = len(receipt.line_items)
        resolved = counts[ResolutionStatus.FUZZY_MATCHED] + counts[ResolutionStatus.BARCODE_MATCHED] + counts[ResolutionStatus.MANUAL_ENTRY]

        return {
            "total_items": total,
            "fuzzy_matched": counts[ResolutionStatus.FUZZY_MATCHED],
            "barcode_matched": counts[ResolutionStatus.BARCODE_MATCHED],
            "manual_entry": counts[ResolutionStatus.MANUAL_ENTRY],
            "unresolved": counts[ResolutionStatus.UNRESOLVED],
            "skipped": counts[ResolutionStatus.SKIPPED],
            "resolution_rate": resolved / total if total > 0 else 0.0,
        }


# Singleton
_resolution_service: Optional[ResolutionService] = None


def get_resolution_service() -> ResolutionService:
    """Get resolution service singleton."""
    global _resolution_service
    if _resolution_service is None:
        _resolution_service = ResolutionService()
    return _resolution_service
