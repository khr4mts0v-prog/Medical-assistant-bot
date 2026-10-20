import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class PendingInboxApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_inbox_api_returns_metadata_without_document_contents(self):
        rows = [{
            "id": 9, "name": "scan.pdf", "created": "2026-10-20",
            "text": "OCR_SENTINEL", "file_bytes": b"FILE_SENTINEL",
            "remote": "/private/family_7/scan.pdf",
            "analysis": {"display_title": "Заключение УЗИ", "primary_type": "заключение УЗИ", "review_required": True},
        }]
        with patch.object(webapp, "family"), patch.object(webapp.db, "pending_documents", return_value=rows), patch.object(webapp.db, "patients", return_value=["Саша"]):
            response = self.client.get("/api/families/7/inbox")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["documents"][0]["title"], "Заключение УЗИ")
        self.assertEqual(payload["patients"], ["Саша"])
        self.assertNotIn("OCR_SENTINEL", response.text)
        self.assertNotIn("FILE_SENTINEL", response.text)
        self.assertNotIn("/private/family_7", response.text)

    def test_inbox_api_requires_family_access(self):
        with patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/7/inbox")
        self.assertEqual(response.status_code, 403)

    def test_inbox_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/7/inbox")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
