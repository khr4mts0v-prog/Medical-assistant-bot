import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class HomeApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_home_api_returns_family_and_patient_metadata_only(self):
        families = [{"id": 7, "name": "Семья"}]
        family = {"id": 7, "name": "Семья"}
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=families),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.tenancy, "role_for_user", return_value="owner"),
            patch.object(webapp.tenancy, "get_family", return_value=family),
            patch.object(webapp.db, "patients", return_value=["Иванов Иван Иванович"]),
            patch.object(webapp.db, "document_count", return_value=3),
            patch.object(webapp.db, "pending_documents", return_value=[{"id": 1}]),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
        ):
            response = self.client.get("/api/home?family_id=7")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_family_id"], 7)
        self.assertEqual(payload["families"][0]["name"], "Семья")
        self.assertEqual(payload["patients"][0]["short_name"], "Иван")
        self.assertEqual(payload["patients"][0]["document_count"], 3)
        self.assertEqual(payload["pending_count"], 1)
        serialized = response.text.lower()
        self.assertNotIn("ocr", serialized)
        self.assertNotIn("storage_path", serialized)
        self.assertNotIn("original_filename", serialized)

    def test_home_api_rejects_family_without_membership(self):
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 7, "name": "Семья"}]),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.tenancy, "role_for_user", return_value=None),
        ):
            response = self.client.get("/api/home?family_id=99")
        self.assertEqual(response.status_code, 403)

    def test_home_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/home")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
