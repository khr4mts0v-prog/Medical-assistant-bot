import os
import re

from PIL import Image, ImageOps, ImageEnhance
import pytesseract


def _correct_perspective(image):
    """Return a deskewed page when a plausible page quadrilateral is found.

    OpenCV is used only for image geometry. OCR remains local Tesseract.
    If detection is uncertain or OpenCV is unavailable, return None and use
    the original image instead.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 900.0 / max(height, width))
    small = cv2.resize(rgb, (max(1, int(width * scale)), max(1, int(height * scale))))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 10, 40)
    kernel_size = max(9, int(max(small.shape[:2]) * 0.027))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    frame_area = small.shape[0] * small.shape[1]
    best = None
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.20 * frame_area:
            continue
        hull = cv2.convexHull(contour)
        perimeter = cv2.arcLength(hull, True)
        for epsilon in (0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
            if len(approx) != 4:
                continue
            points = approx.reshape(4, 2).astype("float32")
            sums = points.sum(axis=1)
            diffs = np.diff(points, axis=1).reshape(-1)
            ordered = np.array([
                points[np.argmin(sums)], points[np.argmin(diffs)],
                points[np.argmax(sums)], points[np.argmax(diffs)]
            ], dtype="float32")
            tl, tr, br, bl = ordered
            avg_width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
            avg_height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
            ratio = avg_width / max(avg_height, 1.0)
            if not 0.40 <= ratio <= 1.10:
                continue
            if best is None or area > best[0]:
                best = (area, ordered)

    if best is None:
        return None

    points = best[1] / scale
    tl, tr, br, bl = points
    out_width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    out_height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if min(out_width, out_height) < 300:
        return None
    out_scale = min(1.0, 2400.0 / max(out_width, out_height))
    out_width = max(1, int(out_width * out_scale))
    out_height = max(1, int(out_height * out_scale))
    destination = np.array([
        [0, 0], [out_width - 1, 0],
        [out_width - 1, out_height - 1], [0, out_height - 1]
    ], dtype="float32")
    transform = cv2.getPerspectiveTransform(points, destination)
    warped = cv2.warpPerspective(np.asarray(ImageOps.exif_transpose(image).convert("RGB")),
                                 transform, (out_width, out_height))
    return Image.fromarray(warped)


def ocr_file(path):
    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")

    def read_image(image):
        image = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(image)))
        # Phone photos often have small text after perspective and page margins.
        # Upscale to improve character recognition, but cap dimensions to bound RAM.
        max_dimension = max(image.size)
        target_dimension = min(max_dimension * 2, 3000)
        if max_dimension and target_dimension != max_dimension:
            scale = target_dimension / max_dimension
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(size, Image.Resampling.LANCZOS)
        image = ImageEnhance.Contrast(image).enhance(1.2)
        return pytesseract.image_to_string(image, lang="rus+eng", config="--psm 6")

    def merge_recovered_fields(original_text, corrected_text):
        """Append only useful metadata/conclusion lines recovered by the second pass."""
        if not corrected_text:
            return original_text
        useful = re.compile(
            r"дата\s+(?:осмотра|исследования|взятия|валидации)|"
            r"ультразвуковое\s+исследование|заключение\s*:|рекомендации\s*:",
            re.IGNORECASE,
        )
        original_normalized = re.sub(r"\s+", " ", original_text).casefold()
        recovered = []
        for line in corrected_text.splitlines():
            line = line.strip()
            if len(line) < 8 or not useful.search(line):
                continue
            normalized = re.sub(r"\s+", " ", line).casefold()
            if normalized not in original_normalized and line not in recovered:
                recovered.append(line)
        if not recovered:
            return original_text
        return original_text.rstrip() + "\n\n--- Дополнительное распознавание после выравнивания страницы ---\n" + "\n".join(recovered)

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
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    text = read_image(image)
                    corrected = _correct_perspective(image)
                    if corrected is not None:
                        text = merge_recovered_fields(text, read_image(corrected))
                result.append(f"--- Страница {i+1} ---\n{text}")
        return "\n\n".join(result)

    with Image.open(path) as image:
        text = read_image(image)
        corrected = _correct_perspective(image)
        if corrected is not None:
            text = merge_recovered_fields(text, read_image(corrected))
        return text
