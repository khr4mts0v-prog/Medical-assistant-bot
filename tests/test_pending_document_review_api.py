import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class PendingDocumentReviewApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_review_api_returns_editor_metadata_without_file_bytes(self):
        pending = {
            "id": 12, "name": "scan.pdf", "created": "2026-10-20", "text": "private OCR",
            "file_bytes": b"secret file bytes", "analysis": {"primary_type": "заключение УЗИ", "display_title": "УЗИ брюшной полости"},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "birth_date": "10-03-2019"}]),
            patch.object(webapp, "_pdf_page_count", return_value=2),
        ):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient_options"], [{"name": "Саша", "birth_date": "10-03-2019"}])
        self.assertEqual(payload["kind"], "заключение УЗИ")
        self.assertEqual(payload["title"], "УЗИ брюшной полости")
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["preview_kind"], "pdf")
        self.assertNotIn("file_bytes", response.text)
        self.assertNotIn("secret file bytes", response.text)

    def test_review_api_enforces_family_access(self):
        with patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 403)

    def test_review_api_returns_404_for_missing_document(self):
        with patch.object(webapp, "family"), patch.object(webapp.db, "get_pending_doc", return_value=None):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 404)

    def test_review_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
