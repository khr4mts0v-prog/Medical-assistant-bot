import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class UnifiedSearchApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_search_returns_safe_document_metadata(self):
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(webapp.tenancy, "get_family", return_value={"id": 1, "name": "Дом"}),
            patch.object(webapp, "family"),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "aliases": []}]),
            patch.object(webapp.db, "search", return_value=[{"id": 7, "kind": "Анализы", "date": "2026-01-02", "text": "гемоглобин", "analysis": {}, "file_bytes": b"private"}]),
            patch.object(webapp, "display_document_title", return_value="Общий анализ крови"),
        ):
            response = self.client.get("/api/search?family_id=1&q=%D0%A1%D0%B0%D1%88%D0%B0%20%D0%B3%D0%B5%D0%BC%D0%BE%D0%B3%D0%BB%D0%BE%D0%B1%D0%B8%D0%BD")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient"], "Саша")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["title"], "Общий анализ крови")
        self.assertNotIn("file_bytes", response.text)
        self.assertNotIn("private", response.text)

    def test_search_denies_family_not_in_membership_list(self):
        with patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 1}]):
            response = self.client.get("/api/search?family_id=2&q=test")
        self.assertEqual(response.status_code, 403)

    def test_search_requires_patient_when_no_name_can_be_resolved(self):
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(webapp.tenancy, "get_family", return_value={"id": 1, "name": "Дом"}),
            patch.object(webapp, "family"),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "aliases": []}]),
        ):
            response = self.client.get("/api/search?family_id=1&q=%D0%B3%D0%B5%D0%BC%D0%BE%D0%B3%D0%BB%D0%BE%D0%B1%D0%B8%D0%BD")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["needs_patient"])
        self.assertEqual(response.json()["patient_choices"], ["Саша"])

    def test_search_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/search")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
