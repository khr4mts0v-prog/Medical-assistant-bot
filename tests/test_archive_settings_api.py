import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class ArchiveSettingsApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_settings_api_returns_owner_and_storage_metadata(self):
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(webapp.tenancy, "get_family", return_value={"id": 1, "name": "Дом"}),
            patch.object(webapp, "family"),
            patch.object(webapp.tenancy, "role_for_user", return_value="owner"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
        ):
            response = self.client.get("/api/settings?family_id=1&updated=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "family_id": 1, "name": "Дом", "role": "owner", "can_rename": True,
            "is_demo": False, "storage_label": "локально на VPS", "disk_connected": False,
            "can_connect_disk": False, "updated": True,
        })

    def test_settings_api_denies_access_to_another_family(self):
        with (
            patch.object(webapp.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(webapp.tenancy, "get_family", return_value={"id": 2, "name": "Чужой"}),
            patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")),
        ):
            response = self.client.get("/api/settings?family_id=2")
        self.assertEqual(response.status_code, 403)

    def test_settings_api_returns_empty_state_without_archives(self):
        with patch.object(webapp.tenancy, "families_for_user", return_value=[]), patch.object(webapp, "is_demo_user", return_value=False):
            response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["family_id"])
        self.assertFalse(response.json()["can_rename"])

    def test_settings_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
