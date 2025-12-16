import pytesseract
from PIL import Image
import logging

def ocr_image(path: str) -> str:
    try:
        text = pytesseract.image_to_string(
            Image.open(path),
            lang="rus"
        )
        return text.strip()
    except Exception as e:
        logging.error(f"OCR error: {e}")
        return ""