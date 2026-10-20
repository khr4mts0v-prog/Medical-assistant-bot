import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class PatientEditorApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_editor_api_returns_authorized_patient_fields(self):
        records = [{
            "name": "Саша", "birth_date": "10-03-2019",
            "aliases": ["Александр", "Саша"], "private": "must not leak",
        }]
        with patch.object(webapp, "family"), patch.object(webapp.db, "patient_records", return_value=records):
            response = self.client.get("/api/families/1/patients/%D0%A1%D0%B0%D1%88%D0%B0/edit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "family_id": 1, "patient": "Саша", "name": "Саша",
            "birth_date": "2019-03-10", "aliases": ["Александр"],
        })
        self.assertNotIn("private", response.text)

    def test_editor_api_denies_family_access(self):
        with patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/1/patients/%D0%A1%D0%B0%D1%88%D0%B0/edit")
        self.assertEqual(response.status_code, 403)

    def test_editor_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/1/patients/%D0%A1%D0%B0%D1%88%D0%B0/edit")
        self.assertEqual(response.status_code, 401)

    def test_editor_api_returns_404_for_missing_patient(self):
        with patch.object(webapp, "family"), patch.object(webapp.db, "patient_records", return_value=[]):
            response = self.client.get("/api/families/1/patients/Missing/edit")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
