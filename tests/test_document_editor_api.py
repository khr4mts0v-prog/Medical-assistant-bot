import os
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class DocumentEditorApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_editor_api_returns_editor_fields_for_authorized_document(self):
        row = {
            "id": 17, "name": "private-original.pdf", "patient": "Саша",
            "kind": "заключение УЗИ", "date": "01-10-2026",
            "text": "OCR text intended for the authorized editor",
            "remote": "/private/family_1/private-original.pdf",
            "analysis": {"display_title": "УЗИ брюшной полости"},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_doc", return_value=row),
            patch.object(webapp, "display_document_title", return_value="УЗИ брюшной полости"),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp, "_read_verified_local_document_pdf", return_value=b"verified-pdf-bytes"),
            patch.object(webapp, "_pdf_page_count", return_value=4),
        ):
            response = self.client.get("/api/families/1/documents/17/edit")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient"], "Саша")
        self.assertEqual(payload["source_name"], "private-original.pdf")
        self.assertEqual(payload["title"], "УЗИ брюшной полости")
        self.assertEqual(payload["ocr_text"], "OCR text intended for the authorized editor")
        self.assertEqual(payload["preview_url"], "/families/1/documents/17/original")
        self.assertEqual(payload["page_count"], 4)
        self.assertIn("не определено", payload["kinds"])

    def test_archived_pdf_page_preview_renders_the_requested_page(self):
        row = {"id": 17, "name": "private-original.pdf", "patient": "Саша", "remote": "/private/family_1/private-original.pdf"}
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_doc", return_value=row),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp, "_read_verified_local_document_pdf", return_value=b"verified-pdf-bytes"),
            patch.object(webapp, "_render_pdf_page", return_value=b"png-page-3") as render_page,
        ):
            response = self.client.get("/families/1/documents/17/preview/page/3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, b"png-page-3")
        render_page.assert_called_once_with(b"verified-pdf-bytes", 3)

    def test_archived_pdf_page_route_renders_real_page_and_rejects_out_of_range(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is unavailable in this test environment")
        import local_storage
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patient_dir = root / "family_1" / "Саша"
            patient_dir.mkdir(parents=True)
            original = patient_dir / "original.pdf"
            with fitz.open() as document:
                for number in range(1, 4):
                    page = document.new_page()
                    page.insert_text((72, 72), f"TEST PAGE {number}")
                document.save(original)
            row = {"id": 17, "name": "original.pdf", "patient": "Саша", "remote": str(original)}
            with (
                patch.object(webapp, "family"),
                patch.object(webapp.db, "get_doc", return_value=row),
                patch.object(webapp, "STORAGE_BACKEND", "local"),
                patch.object(local_storage, "DATA_ROOT", root),
            ):
                response = self.client.get("/families/1/documents/17/preview/page/3")
                out_of_range = self.client.get("/families/1/documents/17/preview/page/4")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "image/png")
            self.assertTrue(response.content.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])))
            self.assertEqual(out_of_range.status_code, 404)

    def test_verified_pdf_reader_accepts_only_expected_patient_directory(self):
        import local_storage
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patient_dir = root / "family_1" / "Саша"
            patient_dir.mkdir(parents=True)
            original = patient_dir / "original.pdf"
            original.write_bytes(b"test-pdf")
            row = {"patient": "Саша", "remote": str(original)}
            with patch.object(local_storage, "DATA_ROOT", root):
                self.assertEqual(webapp._read_verified_local_document_pdf(1, row), b"test-pdf")
                outside = root / "family_1" / "Чужой" / "other.pdf"
                outside.parent.mkdir(parents=True)
                outside.write_bytes(b"other-pdf")
                with self.assertRaises(webapp.HTTPException) as caught:
                    webapp._read_verified_local_document_pdf(1, {"patient": "Саша", "remote": str(outside)})
                self.assertEqual(caught.exception.status_code, 404)

    def test_editor_api_requires_family_access(self):
        with patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/1/documents/17/edit")
        self.assertEqual(response.status_code, 403)

    def test_editor_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/1/documents/17/edit")
        self.assertEqual(response.status_code, 401)

    def test_editor_api_returns_404_for_missing_document(self):
        with patch.object(webapp, "family"), patch.object(webapp.db, "get_doc", return_value=None):
            response = self.client.get("/api/families/1/documents/17/edit")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()