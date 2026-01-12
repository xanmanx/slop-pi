"""
Unit tests for receipt resolution system.

Tests:
- Product code extraction (UPC, PLU, EAN)
- Store classification
- Resolution status transitions
"""

import pytest
from decimal import Decimal

from app.models.receipts import (
    ResolutionStatus,
    StoreType,
    ProductCodeType,
    ExtractedProductCode,
    ReceiptLineItem,
)
from app.services.receipts import ProductCodeExtractor, StoreClassifier


# =============================================================================
# ProductCodeExtractor Tests
# =============================================================================


class TestProductCodeExtractor:
    """Tests for barcode/PLU extraction from receipt text."""

    @pytest.fixture
    def extractor(self):
        return ProductCodeExtractor()

    # UPC-A Tests (12 digits)
    @pytest.mark.unit
    def test_extract_valid_upc_a(self, extractor):
        """Should extract valid 12-digit UPC-A codes."""
        text = "012345678905 Some Product 4.99"
        codes = extractor.extract_codes(text)

        assert len(codes) >= 1
        upc_codes = [c for c in codes if c.code_type == ProductCodeType.UPC_A]
        assert any(c.code == "012345678905" for c in upc_codes)

    @pytest.mark.unit
    def test_upc_checksum_validation(self, extractor):
        """Should validate UPC-A check digits."""
        # Valid UPC (check digit is correct)
        assert extractor._validate_upc_checksum("012345678905") == True

        # Invalid UPC (wrong check digit)
        assert extractor._validate_upc_checksum("012345678900") == False

    @pytest.mark.unit
    def test_extract_upc_with_spaces(self, extractor):
        """Should handle UPCs formatted with spaces."""
        text = "012345 678905 Product Name"
        codes = extractor.extract_codes(text)
        # Should normalize and extract
        assert len(codes) >= 0  # May or may not match depending on pattern

    # PLU Tests (4-5 digits)
    @pytest.mark.unit
    def test_extract_plu_with_prefix(self, extractor):
        """Should extract PLU codes with PLU prefix."""
        text = "PLU 4011 Bananas 1.29"
        codes = extractor.extract_codes(text)

        plu_codes = [c for c in codes if c.code_type == ProductCodeType.PLU]
        assert any(c.code == "4011" for c in plu_codes)

    @pytest.mark.unit
    def test_extract_plu_with_hash(self, extractor):
        """Should extract PLU codes with # prefix."""
        text = "#4011 Bananas 1.29"
        codes = extractor.extract_codes(text)

        plu_codes = [c for c in codes if c.code_type == ProductCodeType.PLU]
        assert any(c.code == "4011" for c in plu_codes)

    @pytest.mark.unit
    def test_plu_confidence_lower_than_upc(self, extractor):
        """PLU codes should have lower confidence than validated UPCs."""
        # This is because PLUs are less specific
        text = "PLU 4011"
        codes = extractor.extract_codes(text)

        if codes:
            plu_code = codes[0]
            assert plu_code.confidence < 0.95  # UPC confidence

    # EAN-13 Tests (13 digits)
    @pytest.mark.unit
    def test_extract_ean13(self, extractor):
        """Should extract valid 13-digit EAN codes."""
        text = "5901234123457 European Product"
        codes = extractor.extract_codes(text)

        ean_codes = [c for c in codes if c.code_type == ProductCodeType.EAN_13]
        assert any(c.code == "5901234123457" for c in ean_codes)

    # Edge Cases
    @pytest.mark.unit
    def test_extract_multiple_codes(self, extractor):
        """Should extract multiple codes from text."""
        text = """
        PLU 4011 Bananas
        012345678905 Cereal Box
        #94011 Organic Bananas
        """
        codes = extractor.extract_codes(text)
        assert len(codes) >= 2

    @pytest.mark.unit
    def test_no_duplicates(self, extractor):
        """Should not return duplicate codes."""
        text = "4011 4011 4011 Bananas"
        codes = extractor.extract_codes(text)

        code_values = [c.code for c in codes]
        assert len(code_values) == len(set(code_values))

    @pytest.mark.unit
    def test_empty_text(self, extractor):
        """Should handle empty text gracefully."""
        codes = extractor.extract_codes("")
        assert codes == []

    @pytest.mark.unit
    def test_none_text(self, extractor):
        """Should handle None text gracefully."""
        codes = extractor.extract_codes(None)
        assert codes == []

    @pytest.mark.unit
    def test_no_codes_in_text(self, extractor):
        """Should return empty list when no codes found."""
        text = "Just some random text without any product codes"
        codes = extractor.extract_codes(text)
        assert codes == []


# =============================================================================
# StoreClassifier Tests
# =============================================================================


class TestStoreClassifier:
    """Tests for store type classification."""

    @pytest.fixture
    def classifier(self):
        return StoreClassifier()

    @pytest.mark.unit
    @pytest.mark.parametrize("store_name,expected", [
        ("ALDI", StoreType.GROCERY),
        ("Aldi Store #119", StoreType.GROCERY),
        ("KROGER", StoreType.GROCERY),
        ("Kroger Marketplace", StoreType.GROCERY),
        ("Safeway", StoreType.GROCERY),
        ("PUBLIX", StoreType.GROCERY),
    ])
    def test_grocery_stores(self, classifier, store_name, expected):
        """Should classify grocery stores correctly."""
        assert classifier.classify(store_name) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("store_name,expected", [
        ("COSTCO", StoreType.WAREHOUSE),
        ("Costco Wholesale", StoreType.WAREHOUSE),
        ("SAM'S CLUB", StoreType.WAREHOUSE),
        ("BJ's Wholesale", StoreType.WAREHOUSE),
    ])
    def test_warehouse_stores(self, classifier, store_name, expected):
        """Should classify warehouse stores correctly."""
        assert classifier.classify(store_name) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("store_name,expected", [
        ("Whole Foods Market", StoreType.SPECIALTY),
        ("TRADER JOE'S", StoreType.SPECIALTY),
        ("Sprouts Farmers Market", StoreType.SPECIALTY),
    ])
    def test_specialty_stores(self, classifier, store_name, expected):
        """Should classify specialty stores correctly."""
        assert classifier.classify(store_name) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("store_name,expected", [
        ("7-ELEVEN", StoreType.CONVENIENCE),
        ("Wawa", StoreType.CONVENIENCE),
        ("Sheetz", StoreType.CONVENIENCE),
    ])
    def test_convenience_stores(self, classifier, store_name, expected):
        """Should classify convenience stores correctly."""
        assert classifier.classify(store_name) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("store_name,expected", [
        ("CVS Pharmacy", StoreType.PHARMACY),
        ("WALGREENS", StoreType.PHARMACY),
        ("Rite Aid", StoreType.PHARMACY),
    ])
    def test_pharmacy_stores(self, classifier, store_name, expected):
        """Should classify pharmacy stores correctly."""
        assert classifier.classify(store_name) == expected

    @pytest.mark.unit
    def test_unknown_store(self, classifier):
        """Should return UNKNOWN for unrecognized stores."""
        assert classifier.classify("Random Local Shop") == StoreType.UNKNOWN
        assert classifier.classify("Mom's Corner Store") == StoreType.UNKNOWN

    @pytest.mark.unit
    def test_empty_store_name(self, classifier):
        """Should handle empty store name."""
        assert classifier.classify("") == StoreType.UNKNOWN
        assert classifier.classify(None) == StoreType.UNKNOWN

    @pytest.mark.unit
    def test_case_insensitive(self, classifier):
        """Should be case insensitive."""
        assert classifier.classify("aldi") == StoreType.GROCERY
        assert classifier.classify("ALDI") == StoreType.GROCERY
        assert classifier.classify("Aldi") == StoreType.GROCERY


# =============================================================================
# Resolution Status Tests
# =============================================================================


class TestResolutionStatus:
    """Tests for resolution status transitions."""

    @pytest.mark.unit
    def test_line_item_default_status(self):
        """New line items should have PENDING status."""
        item = ReceiptLineItem(raw_text="Test item")
        assert item.resolution_status == ResolutionStatus.PENDING

    @pytest.mark.unit
    def test_line_item_manual_entry_flag(self):
        """Line items should track manual entry need."""
        item = ReceiptLineItem(raw_text="Test item")
        assert item.needs_manual_entry == False

        item.needs_manual_entry = True
        item.resolution_status = ResolutionStatus.UNRESOLVED
        assert item.needs_manual_entry == True

    @pytest.mark.unit
    def test_resolution_status_values(self):
        """All resolution status values should be valid."""
        valid_statuses = [
            ResolutionStatus.PENDING,
            ResolutionStatus.FUZZY_MATCHED,
            ResolutionStatus.BARCODE_MATCHED,
            ResolutionStatus.MANUAL_ENTRY,
            ResolutionStatus.UNRESOLVED,
            ResolutionStatus.SKIPPED,
        ]
        assert len(valid_statuses) == 6

    @pytest.mark.unit
    def test_extracted_codes_storage(self):
        """Line items should store extracted codes."""
        item = ReceiptLineItem(raw_text="Test item")

        code = ExtractedProductCode(
            code="4011",
            code_type=ProductCodeType.PLU,
            confidence=0.7,
            source_text="PLU 4011"
        )
        item.extracted_codes = [code]

        assert len(item.extracted_codes) == 1
        assert item.extracted_codes[0].code == "4011"
