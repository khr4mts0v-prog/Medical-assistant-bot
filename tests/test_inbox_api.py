import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class InboxApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_inbox_api_returns_only_minimal_metadata(self):
        pending = [{"id": 12, "name": "scan.pdf", "created": "2026-10-20", "text": "private OCR", "file_bytes": b"secret"}]
        with (
            patch.object(webapp, "family", return_value={"id": 7, "name": "Семья"}),
            patch.object(webapp.db, "pending_documents", return_value=pending),
            patch.object(webapp.db, "patients", return_value=["Иванов Иван Иванович"]),
        ):
            response = self.client.get("/api/families/7/inbox")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["family_id"], 7)
        self.assertEqual(payload["patients"], [{"name": "Иванов Иван Иванович"}])
        self.assertEqual(payload["documents"], [{"id": 12, "name": "scan.pdf", "created": "2026-10-20"}])
        self.assertNotIn("private OCR", response.text)
        self.assertNotIn("file_bytes", response.text)
        self.assertNotIn("storage_path", response.text)

    def test_inbox_api_enforces_family_access(self):
        from fastapi import HTTPException
        with patch.object(webapp, "family", side_effect=HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/99/inbox")
        self.assertEqual(response.status_code, 403)

    def test_inbox_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/7/inbox")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
