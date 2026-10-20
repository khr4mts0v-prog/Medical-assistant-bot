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


    def test_intelligent_search_passes_confirmed_patient_memory_to_answer_generation(self):
        from datetime import date
        accepted_text = "Пользователь подтвердил длительный приём препарата X"
        snapshot = {
            "patient": "Саша",
            "profile": {},
            "document_count": 0,
            "documents": [],
            "lab_results": [],
            "diagnoses_mentioned": [],
            "medications_mentioned": [],
            "manual_facts": [{
                "id": 77, "text": accepted_text, "category": "medication",
                "date": date.today().isoformat(), "memory_key": "medication",
                "origin": "approved_document", "status": "active",
                "source": {"document_id": 55, "name": "Выписка", "date": "2026-10-01", "kind": "выписка"},
                "created_by": 123, "created_at": "2026-10-20T07:00:00Z",
                "updated_at": "2026-10-20T07:00:00Z",
            }],
            "pending_proposals": [],
        }
        captured = {}

        def fake_answer(question, people, rows, history, memory_context="", trace_id=None):
            captured["question"] = question
            captured["people"] = people
            captured["memory_context"] = memory_context
            return {
                "answer": "Ответ подготовлен с учётом подтверждённой памяти.",
                "missing_documents": [], "limitations": [],
                "data_completeness": "complete", "memory_updates": [],
            }

        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="owner"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1, "name": "Дом"}),
            patch.object(assistant_routes.db, "patients", return_value=["Саша"]),
            patch.object(assistant_routes.db, "patient_records", return_value=[{"name": "Саша", "aliases": []}]),
            patch.object(assistant_routes.ai_consent, "get", return_value={"granted": True}),
            patch.object(assistant_routes, "provider_config", return_value=("test", "test-token", "", "test-model", "")),
            patch.object(assistant_routes, "_planner", return_value={"search_terms": [], "document_types": [], "allow_full_history": False, "original_question": ""}),
            patch.object(assistant_routes, "_retrieve", return_value=[]),
            patch.object(assistant_routes.patient_memory, "get_snapshot", return_value=snapshot),
            patch.object(assistant_routes, "_structured_archive_answer", side_effect=fake_answer),
            patch.object(assistant_routes.patient_memory, "get_proposals", return_value=[]),
            patch.object(assistant_routes.ai_trace_log, "start", return_value="test-trace"),
            patch.object(assistant_routes.ai_trace_log, "emit"),
            patch.object(assistant_routes.ai_trace_log, "emit_full"),
            patch.object(assistant_routes.ai_interaction_log, "record"),
        ):
            response = self.client.post("/api/intelligent-search", json={
                "family_id": 1, "patient_scope": "Саша",
                "query": "Что известно о Саше и препарате?",
            })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "analysis")
        self.assertEqual(captured["people"], ["Саша"])
        self.assertIn(accepted_text, captured["memory_context"])
        self.assertIn("документ ID 55", captured["memory_context"])
        self.assertNotIn("другой пациент", captured["memory_context"].casefold())


if __name__ == "__main__":
    unittest.main()
