import pytesseract
import logging

# ----------------------
# OCR для документов
# ----------------------
def ocr_file(file_path: str) -> str:
    """
    Преобразует изображение или PDF в текст через pytesseract.
    """
    try:
        text = pytesseract.image_to_string(file_path, lang='rus+eng')
        logging.info(f"OCR успешно выполнен для файла: {file_path}")
        return text
    except Exception as e:
        logging.error(f"OCR ошибка для файла {file_path}: {e}")
        return ""