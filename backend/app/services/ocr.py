"""
On-device OCR using Tesseract.

Install:
    sudo apt install tesseract-ocr
    pip install pytesseract pillow
"""

import logging
from PIL import Image
import io
from typing import Optional

logger = logging.getLogger(__name__)

# Check if tesseract is available
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed. Run: pip install pytesseract")


def ocr_image(image_bytes: bytes) -> Optional[str]:
    """
    Extract text from image using Tesseract OCR.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, etc.)

    Returns:
        Extracted text or None if OCR fails
    """
    if not TESSERACT_AVAILABLE:
        logger.error("Tesseract not available")
        return None

    try:
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Run OCR
        text = pytesseract.image_to_string(image)

        return text

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return None


def preprocess_receipt_image(image_bytes: bytes) -> bytes:
    """
    Preprocess receipt image for better OCR accuracy.

    Optional enhancements you can add:
    - Grayscale conversion
    - Contrast enhancement
    - Thresholding
    - Deskewing
    """
    # TODO: Add preprocessing if needed
    return image_bytes
