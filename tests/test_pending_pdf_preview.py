import sys
import types
import unittest
from unittest.mock import patch

import webapp


class _FakePixmap:
    def tobytes(self, _format):
        return b"png-bytes"


class _FakePage:
    def get_pixmap(self, **_kwargs):
        return _FakePixmap()


class _FakeDocument:
    def __init__(self, pages=3):
        self.pages = pages
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def __len__(self):
        return self.pages
    def load_page(self, index):
        if index < 0 or index >= self.pages:
            raise IndexError(index)
        return _FakePage()


class PendingPdfPreviewTests(unittest.TestCase):
    def setUp(self):
        self.fake_fitz = types.SimpleNamespace(
            open=lambda **_kwargs: _FakeDocument(),
            Matrix=lambda *_args: object(),
        )

    def test_ocr_preview_formats_serialized_page_records(self):
        self.assertEqual(
            webapp._format_ocr_preview("{'page': 2, 'text': 'Гемоглобин 120'}"),
            "--- Страница 2 ---\nГемоглобин 120",
        )
        self.assertEqual(
            webapp._format_ocr_preview("[{'page': 1, 'text': 'Первая'}, {'page': 2, 'text': 'Вторая'}]"),
            "--- Страница 1 ---\nПервая\n\n--- Страница 2 ---\nВторая",
        )

    def test_ocr_preview_preserves_plain_text_and_unknown_structures(self):
        ordinary = "Обычный OCR-текст"
        unknown = "{'unexpected': 'value'}"
        self.assertEqual(webapp._format_ocr_preview(ordinary), ordinary)
        self.assertEqual(webapp._format_ocr_preview(unknown), unknown)

    def test_document_editor_api_keeps_raw_ocr_when_formatting_display(self):
        raw = "{'page': 2, 'text': 'Гемоглобин 120'}"
        document = {
            "id": 2, "name": "blood.pdf", "patient": "Тестовый пациент", "kind": "не определено",
            "date": "", "text": raw, "remote": "", "analysis": {"display_title": "Анализ крови"},
        }
        with patch("webapp.family"), patch("webapp.db.get_doc", return_value=document):
            response = webapp.document_editor_api(fid=1, doc_id=2, uid=9)
        self.assertEqual(response["ocr_text"], "--- Страница 2 ---\nГемоглобин 120")
        self.assertEqual(response["ocr_text_raw"], raw)

    def test_page_count_reads_full_document(self):
        with patch.dict(sys.modules, {"fitz": self.fake_fitz}):
            self.assertEqual(webapp._pdf_page_count(b"pdf-bytes"), 3)

    def test_each_requested_page_renders_to_png(self):
        with patch.dict(sys.modules, {"fitz": self.fake_fitz}):
            self.assertEqual(webapp._render_pdf_page(b"pdf-bytes", 3), b"png-bytes")
            with self.assertRaises(IndexError):
                webapp._render_pdf_page(b"pdf-bytes", 4)

    def test_manual_classification_includes_every_page_in_the_preview(self):
        pending = {"id": 8, "name": "three-pages.pdf", "file_bytes": b"pdf-bytes",
                   "text": "OCR from all pages", "analysis": {"primary_type": "не определено"}}
        with patch("webapp.family"), \
             patch("webapp.db.get_pending_doc", return_value=pending), \
             patch("webapp.db.patient_records", return_value=[]), \
             patch("webapp._pdf_page_count", return_value=3):
            response = webapp.review_pending_document(fid=1, pending_id=8, uid=9)
        html = response.body.decode("utf-8")
        self.assertIn("Предпросмотр PDF · 3 стр.", html)
        for page in (1, 2, 3):
            self.assertIn(f"/preview/page/{page}", html)
            self.assertIn(f"Страница {page} из 3", html)


if __name__ == "__main__":
    unittest.main()