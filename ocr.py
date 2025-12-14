import pytesseract
import logging

def ocr_file(file_path):
    try:
        text = pytesseract.image_to_string(file_path, lang="rus")
        return text
    except Exception as e:
        logging.error(f"OCR error: {e}")
        return ""