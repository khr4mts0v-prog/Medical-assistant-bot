import os
from PIL import Image, ImageOps, ImageEnhance
import pytesseract

def ocr_file(path):
    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")
    def read_image(image):
        image = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(image)))
        return pytesseract.image_to_string(ImageEnhance.Contrast(image).enhance(1.2), lang="rus+eng")
    if path.lower().endswith(".pdf"):
        import fitz
        result = []
        with fitz.open(path) as pdf:
            max_pages = max(1, int(os.getenv("MAX_PDF_PAGES", "100")))
            if len(pdf) > max_pages:
                raise ValueError(f"PDF has {len(pdf)} pages; limit is {max_pages}")
            for i, page in enumerate(pdf):
                text = page.get_text().strip()
                if len(text) < 25:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    text = read_image(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                result.append(f"--- Страница {i+1} ---\n{text}")
        return "\n\n".join(result)
    with Image.open(path) as image:
        return read_image(image)
