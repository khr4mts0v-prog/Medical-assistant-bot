import pytesseract
from PIL import Image
import logging
import os

def ocr_file(file_path: str) -> str:
    """
    Распознаёт текст из изображения или PDF-файла.
    Возвращает текст.
    """
    try:
        # Если файл — изображение
        if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif")):
            text = pytesseract.image_to_string(Image.open(file_path), lang="rus+eng")
        # Если файл — PDF
        elif file_path.lower().endswith(".pdf"):
            try:
                import pdf2image
            except ImportError:
                logging.error("Для обработки PDF необходимо установить pdf2image: pip install pdf2image")
                return ""
            images = pdf2image.convert_from_path(file_path)
            text = ""
            for img in images:
                text += pytesseract.image_to_string(img, lang="rus+eng") + "\n"
        else:
            logging.warning(f"Неизвестный тип файла для OCR: {file_path}")
            return ""
        return text.strip()
    except Exception as e:
        logging.error(f"OCR error for file {file_path}: {e}")
        return ""