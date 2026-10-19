import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class PatientDetailApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_patient_detail_returns_safe_structured_documents(self):
        rows = [{
            "id": 17, "name": "private-original.pdf", "kind": "УЗИ", "date": "01-10-2026",
            "added": "2026-10-02", "remote": "/private/family_1/private-original.pdf",
            "ocr_remote": "/private/family_1/private-original.txt", "text": "private OCR text",
            "analysis": {"review_required": True}, "keywords": [],
        }]
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp.db, "search", return_value=rows),
            patch.object(webapp, "document_card_metadata", return_value={"metadata": "Источник: УЗИ", "finding": "Краткое заключение"}),
            patch.object(webapp, "display_document_title", return_value="УЗИ брюшной полости"),
        ):
            response = self.client.get("/api/families/1/patients/%D0%A1%D0%B0%D1%88%D0%B0?view=tree")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient"], "Саша")
        self.assertEqual(payload["view"], "tree")
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["documents"][0]["id"], 17)
        self.assertEqual(payload["documents"][0]["title"], "УЗИ брюшной полости")
        serialized = response.text
        self.assertNotIn("private-original.pdf", serialized)
        self.assertNotIn("private OCR text", serialized)
        self.assertNotIn("/private/family_1", serialized)

    def test_unknown_patient_returns_404(self):
        with patch.object(webapp, "family"), patch.object(webapp.db, "patients", return_value=[]):
            response = self.client.get("/api/families/1/patients/unknown")
        self.assertEqual(response.status_code, 404)

    def test_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/1/patients/Sasha")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
