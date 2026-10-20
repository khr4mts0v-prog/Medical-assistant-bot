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


class PatientMemoryProposalApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_accept_action_is_scoped_to_authorized_family_and_named_patient(self):
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.db, "patients", return_value=["Саша"]),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="owner"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1}),
            patch.object(assistant_routes.patient_memory, "accept_proposal", return_value=77) as accept,
        ):
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 1, "patient": "Саша", "proposal_id": 9, "action": "accept",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "status": "accepted", "fact_id": 77})
        accept.assert_called_once_with(1, "Саша", 9, 123)

    def test_proposal_action_denies_family_outside_membership(self):
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.patient_memory, "accept_proposal") as accept,
        ):
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 2, "patient": "Саша", "proposal_id": 9, "action": "accept",
            })
        self.assertEqual(response.status_code, 403)
        accept.assert_not_called()

    def test_proposal_action_rejects_patient_not_in_family(self):
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.db, "patients", return_value=["Маша"]),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="owner"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1}),
            patch.object(assistant_routes.patient_memory, "accept_proposal") as accept,
        ):
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 1, "patient": "Саша", "proposal_id": 9, "action": "accept",
            })
        self.assertEqual(response.status_code, 400)
        accept.assert_not_called()

    def test_reject_action_never_calls_accept(self):
        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.db, "patients", return_value=["Саша"]),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="owner"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1}),
            patch.object(assistant_routes.patient_memory, "reject_proposal") as reject,
            patch.object(assistant_routes.patient_memory, "accept_proposal") as accept,
        ):
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 1, "patient": "Саша", "proposal_id": 9, "action": "reject",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "status": "rejected"})
        reject.assert_called_once_with(1, "Саша", 9)
        accept.assert_not_called()


if __name__ == "__main__":
    unittest.main()
