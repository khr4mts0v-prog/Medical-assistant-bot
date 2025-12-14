import pytesseract
from pdf2image import convert_from_path
from PIL import Image

def ocr_image(path):
    return pytesseract.image_to_string(Image.open(path), lang="rus")

def ocr_pdf(path):
    text = ""
    for page in convert_from_path(path, dpi=200):
        text += pytesseract.image_to_string(page, lang="rus")
    return text
