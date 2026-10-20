import os
import unittest
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
        ):
            response = self.client.get("/api/families/1/documents/17/edit")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient"], "Саша")
        self.assertEqual(payload["source_name"], "private-original.pdf")
        self.assertEqual(payload["title"], "УЗИ брюшной полости")
        self.assertEqual(payload["ocr_text"], "OCR text intended for the authorized editor")
        self.assertEqual(payload["preview_url"], "/families/1/documents/17/original")
        self.assertIn("не определено", payload["kinds"])

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
