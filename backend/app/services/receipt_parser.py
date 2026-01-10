"""
Custom receipt parser.

YOUR JOB: Implement the parsing logic in parse_receipt_text()

The OCR gives you raw text like this (from your ALDI receipt):

    ALDI
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
    (G) 0.22lb -    (T) 0.01lb
    (N) 0.21 lb x   0.89/lb
    445412 Italian Loaf         3.79 FA

    SUBTOTAL                   63.50
    A:Taxable @0.00%            0.00
    AMOUNT DUE                 63.50
    T O T A L                $ 63.50
    20 ITEMS
    Debit Card               $ 63.50

Your job is to extract:
1. Store name (e.g., "ALDI")
2. Store address
3. Line items (product code, name, price, quantity)
4. Totals (subtotal, tax, total)
5. Date if present

Look at the patterns. ALDI uses:
- 6-digit product codes
- "FA" suffix on prices (Food Allowance? idk)
- "x" for quantity multipliers
- Prices right-aligned

Start simple. Get ALDI working first, then generalize.
"""

import re
import logging
from datetime import date
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedLineItem:
    """A single item from the receipt."""
    raw_text: str
    product_code: Optional[str] = None
    name: Optional[str] = None
    quantity: int = 1
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None


@dataclass
class ParsedReceiptData:
    """Structured data extracted from receipt text."""
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    purchase_date: Optional[date] = None
    line_items: list[ParsedLineItem] = None
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Optional[Decimal] = None
    raw_text: str = ""

    def __post_init__(self):
        if self.line_items is None:
            self.line_items = []


def parse_receipt_text(ocr_text: str) -> ParsedReceiptData:
    """
    Parse raw OCR text into structured receipt data.

    THIS IS YOUR FUNCTION TO IMPLEMENT.

    Args:
        ocr_text: Raw text from OCR

    Returns:
        ParsedReceiptData with extracted fields

    Tips:
    - Start by printing ocr_text to see what you're working with
    - Use regex to find patterns
    - Handle errors gracefully (receipts are messy)
    - Test with real receipts from your grocery trips
    """

    result = ParsedReceiptData(raw_text=ocr_text)

    # ==========================================================
    # YOUR CODE HERE
    # ==========================================================
    #
    # Example to get you started (delete this and write your own):
    #
    # lines = ocr_text.strip().split('\n')
    #
    # # First non-empty line is usually store name
    # for line in lines:
    #     if line.strip():
    #         result.store_name = line.strip()
    #         break
    #
    # # Find line items (ALDI pattern: 6 digits + name + price + FA)
    # item_pattern = r'^(\d{6})\s+(.+?)\s+(\d+\.\d{2})\s*FA'
    # for line in lines:
    #     match = re.match(item_pattern, line.strip())
    #     if match:
    #         code, name, price = match.groups()
    #         result.line_items.append(ParsedLineItem(
    #             raw_text=line,
    #             product_code=code,
    #             name=name.strip(),
    #             total_price=Decimal(price),
    #         ))
    #
    # ==========================================================

    # TODO: Implement your parser
    logger.warning("parse_receipt_text() not implemented yet!")

    return result


def detect_store_type(ocr_text: str) -> str:
    """
    Detect which store the receipt is from.

    Returns store identifier like 'aldi', 'kroger', 'walmart', etc.
    Returns 'unknown' if can't determine.

    You might want different parsing logic per store.
    """
    text_lower = ocr_text.lower()

    if 'aldi' in text_lower:
        return 'aldi'
    elif 'kroger' in text_lower:
        return 'kroger'
    elif 'walmart' in text_lower:
        return 'walmart'
    elif 'meijer' in text_lower:
        return 'meijer'
    # Add more stores as you encounter them

    return 'unknown'
