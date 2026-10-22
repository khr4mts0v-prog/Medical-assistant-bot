import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import assistant_routes
import webapp


class IntelligentSearchPatientAmbiguityApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_shared_nickname_returns_clarification_without_searching_or_calling_model(self):
        patient_records = [
            {"name": "Александр Иванов", "aliases": ["Александр Иванов", "Саша"]},
            {"name": "Александр Петров", "aliases": ["Александр Петров", "Саша"]},
        ]
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes, "family_guard"),
            patch.object(assistant_routes.db, "patients", return_value=["Александр Иванов", "Александр Петров"]),
            patch.object(assistant_routes.db, "patient_records", return_value=patient_records),
            patch.object(assistant_routes.db, "search") as search,
            patch.object(assistant_routes, "chat_completion") as model,
        ):
            response = self.client.post(
                "/api/intelligent-search",
                json={"family_id": 1, "query": "Расскажи про Сашу"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "analysis")
        self.assertIn("Уточни", payload["answer"])
        self.assertIn("нескольким пациентам", payload["answer"])
        self.assertEqual(payload["documents"], [])
        self.assertEqual(payload["data_completeness"], "insufficient")
        search.assert_not_called()
        model.assert_not_called()

    def test_patient_scope_cannot_be_used_to_select_unregistered_person(self):
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes, "family_guard"),
            patch.object(assistant_routes.db, "patients", return_value=["Олег", "Саша"]),
            patch.object(assistant_routes.db, "patient_records", return_value=[
                {"name": "Олег", "aliases": ["Олег"]},
                {"name": "Саша", "aliases": ["Саша"]},
            ]),
        ):
            response = self.client.post(
                "/api/intelligent-search",
                json={"family_id": 1, "patient_scope": "Мария", "query": "Расскажи про неё"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("не найден", response.json()["detail"].casefold())


if __name__ == "__main__":
    unittest.main()
