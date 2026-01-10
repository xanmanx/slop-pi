#!/usr/bin/env python3
"""
Test script for developing your receipt parser.

Usage:
    python test_parser.py /path/to/receipt.jpg

This will:
1. Run OCR on the image
2. Print the raw text (so you can see what you're working with)
3. Run your parser
4. Print the results
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.ocr import ocr_image
from app.services.receipt_parser import parse_receipt_text, detect_store_type


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_parser.py <receipt_image>")
        print("Example: python test_parser.py ~/receipt.jpg")
        sys.exit(1)

    image_path = Path(sys.argv[1]).expanduser()

    if not image_path.exists():
        print(f"File not found: {image_path}")
        sys.exit(1)

    print(f"Processing: {image_path}")
    print("=" * 60)

    # Read image
    image_bytes = image_path.read_bytes()

    # Run OCR
    print("\n[1] Running OCR...")
    raw_text = ocr_image(image_bytes)

    if not raw_text:
        print("OCR failed!")
        sys.exit(1)

    print("\n[2] Raw OCR text:")
    print("-" * 40)
    print(raw_text)
    print("-" * 40)

    # Detect store
    store = detect_store_type(raw_text)
    print(f"\n[3] Detected store: {store}")

    # Parse
    print("\n[4] Running your parser...")
    result = parse_receipt_text(raw_text)

    # Show results
    print("\n[5] Parsed results:")
    print("-" * 40)
    print(f"Store: {result.store_name}")
    print(f"Address: {result.store_address}")
    print(f"Date: {result.purchase_date}")
    print(f"Items: {len(result.line_items)}")

    for i, item in enumerate(result.line_items):
        print(f"  [{i+1}] {item.product_code or '??????'} | {item.name or 'Unknown'} | ${item.total_price or '?.??'}")

    print(f"Subtotal: ${result.subtotal or '?.??'}")
    print(f"Tax: ${result.tax or '?.??'}")
    print(f"Total: ${result.total or '?.??'}")
    print("-" * 40)


if __name__ == "__main__":
    main()
