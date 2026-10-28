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


class PatientSwitchDialogueApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_switching_from_oleg_to_sasha_keeps_question_but_drops_oleg_answer_and_documents(self):
        rows = {
            "Олег": [{
                "id": 10, "patient": "Олег", "name": "oleg-private.pdf",
                "kind": "заключение", "date": "2026-10-01",
                "text": "OLEGS_PRIVATE_MEDICAL_SOURCE",
            }],
            "Саша": [{
                "id": 20, "patient": "Саша", "name": "sasha-private.pdf",
                "kind": "заключение", "date": "2026-10-02",
                "text": "SASHAS_PRIVATE_MEDICAL_SOURCE",
            }],
        }
        captured = {}

        def capture_answer(question, patients, documents, history, memory_context="", trace_id=None):
            captured.update({
                "question": question,
                "patients": list(patients),
                "documents": list(documents),
                "history": list(history),
                "memory_context": memory_context,
            })
            return {
                "answer": "Сводка по Саше готова.",
                "missing_documents": [],
                "limitations": [],
                "data_completeness": "complete",
                "memory_updates": [],
                "generation_status": "complete",
            }

        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="admin"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1}),
            patch.object(assistant_routes.db, "patients", return_value=["Олег", "Саша"]),
            patch.object(assistant_routes.db, "patient_records", return_value=[
                {"name": "Олег", "aliases": ["Олег"]},
                {"name": "Саша", "aliases": ["Саша"]},
            ]),
            patch.object(assistant_routes.ai_consent, "get", return_value={"granted": True}),
            patch.object(assistant_routes.ai_consent, "set_consent"),
            patch.object(assistant_routes, "provider_config", return_value=("test-provider", "test-token", "", "test-model", "")),
            patch.object(assistant_routes, "_planner", return_value={
                "search_terms": ["заключение"], "document_types": [],
                "allow_full_history": False, "original_question": "А теперь по Саше",
            }),
            patch.object(assistant_routes, "_retrieve", side_effect=lambda fid, patient, plan, result_limit=15: rows[patient]),
            patch.object(assistant_routes, "_structured_archive_answer", side_effect=capture_answer),
            patch.object(assistant_routes.patient_memory, "get_snapshot", return_value={"profile": {}, "facts": []}),
            patch.object(assistant_routes.patient_memory, "to_context", return_value="SASHAS_MEMORY_ONLY"),
            patch.object(assistant_routes.patient_memory, "get_proposals", return_value=[]),
            patch.object(assistant_routes.ai_interaction_log, "record"),
        ):
            response = self.client.post(
                "/api/intelligent-search",
                json={
                    "family_id": 1,
                    "query": "А теперь по Саше",
                    "consent": True,
                    "conversation": [{
                        "family_id": 1,
                        "patient_scope": None,
                        "question": "Расскажи про Олега",
                        "answer": "OLEGS_PRIVATE_PREVIOUS_ANSWER",
                    }],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "Сводка по Саше готова.")
        self.assertEqual(captured["patients"], ["Саша"])
        self.assertEqual([row["id"] for row in captured["documents"]], [20])
        self.assertEqual([row["patient"] for row in captured["documents"]], ["Саша"])
        self.assertEqual(captured["history"], ["Предыдущий вопрос: Расскажи про Олега"])
        self.assertNotIn("OLEGS_PRIVATE_PREVIOUS_ANSWER", repr(captured))
        self.assertNotIn("OLEGS_PRIVATE_MEDICAL_SOURCE", repr(captured))
        self.assertIn("SASHAS_PRIVATE_MEDICAL_SOURCE", repr(captured["documents"]))
        self.assertEqual(captured["memory_context"], "Пациент: Саша\nSASHAS_MEMORY_ONLY")


    def test_switching_from_sasha_to_oleg_keeps_question_but_drops_sasha_answer_and_documents(self):
        rows = {
            "Саша": [{
                "id": 20, "patient": "Саша", "name": "sasha-private.pdf",
                "kind": "заключение", "date": "2026-10-01",
                "text": "SASHAS_PRIVATE_MEDICAL_SOURCE",
            }],
            "Олег": [{
                "id": 10, "patient": "Олег", "name": "oleg-private.pdf",
                "kind": "заключение", "date": "2026-10-02",
                "text": "OLEGS_PRIVATE_MEDICAL_SOURCE",
            }],
        }
        captured = {}

        def capture_answer(question, patients, documents, history, memory_context="", trace_id=None):
            captured.update({
                "question": question,
                "patients": list(patients),
                "documents": list(documents),
                "history": list(history),
                "memory_context": memory_context,
            })
            return {
                "answer": "Сводка по Олегу готова.",
                "missing_documents": [],
                "limitations": [],
                "data_completeness": "complete",
                "memory_updates": [],
                "generation_status": "complete",
            }

        with (
            patch.object(assistant_routes.tenancy, "families_for_user", return_value=[{"id": 1}]),
            patch.object(assistant_routes.tenancy, "role_for_user", return_value="admin"),
            patch.object(assistant_routes.tenancy, "get_family", return_value={"id": 1}),
            patch.object(assistant_routes.db, "patients", return_value=["Саша", "Олег"]),
            patch.object(assistant_routes.db, "patient_records", return_value=[
                {"name": "Саша", "aliases": ["Саша"]},
                {"name": "Олег", "aliases": ["Олег"]},
            ]),
            patch.object(assistant_routes.ai_consent, "get", return_value={"granted": True}),
            patch.object(assistant_routes.ai_consent, "set_consent"),
            patch.object(assistant_routes, "provider_config", return_value=("test-provider", "test-token", "", "test-model", "")),
            patch.object(assistant_routes, "_planner", return_value={
                "search_terms": ["заключение"], "document_types": [],
                "allow_full_history": False, "original_question": "А теперь по Олегу",
            }),
            patch.object(assistant_routes, "_retrieve", side_effect=lambda fid, patient, plan, result_limit=15: rows[patient]),
            patch.object(assistant_routes, "_structured_archive_answer", side_effect=capture_answer),
            patch.object(assistant_routes.patient_memory, "get_snapshot", return_value={"profile": {}, "facts": []}),
            patch.object(assistant_routes.patient_memory, "to_context", return_value="OLEGS_MEMORY_ONLY"),
            patch.object(assistant_routes.patient_memory, "get_proposals", return_value=[]),
            patch.object(assistant_routes.ai_interaction_log, "record"),
        ):
            response = self.client.post(
                "/api/intelligent-search",
                json={
                    "family_id": 1,
                    "query": "А теперь по Олегу",
                    "consent": True,
                    "conversation": [{
                        "family_id": 1,
                        "patient_scope": None,
                        "question": "Расскажи про Сашу",
                        "answer": "SASHAS_PRIVATE_PREVIOUS_ANSWER",
                    }],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "Сводка по Олегу готова.")
        self.assertEqual(captured["patients"], ["Олег"])
        self.assertEqual([row["id"] for row in captured["documents"]], [10])
        self.assertEqual([row["patient"] for row in captured["documents"]], ["Олег"])
        self.assertEqual(captured["history"], ["Предыдущий вопрос: Расскажи про Сашу"])
        self.assertNotIn("SASHAS_PRIVATE_PREVIOUS_ANSWER", repr(captured))
        self.assertNotIn("SASHAS_PRIVATE_MEDICAL_SOURCE", repr(captured))
        self.assertIn("OLEGS_PRIVATE_MEDICAL_SOURCE", repr(captured["documents"]))
        self.assertEqual(captured["memory_context"], "Пациент: Олег\\nOLEGS_MEMORY_ONLY")



if __name__ == "__main__":
    unittest.main()
