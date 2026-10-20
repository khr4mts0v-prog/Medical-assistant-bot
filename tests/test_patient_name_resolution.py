import json
import unittest
from unittest.mock import patch

import assistant_routes


class PatientNameResolutionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {
                "id": 11,
                "name": "Александр Иванов",
                "birth_date": "2019-03-10",
                "aliases": ["Александр Иванов", "Саша", "Сашка"],
            },
            {
                "id": 12,
                "name": "Олег Петров",
                "birth_date": "1990-01-02",
                "aliases": ["Олег Петров", "Олег", "Олежка"],
            },
        ]

    def test_unresolved_reference_detection_accepts_lowercase_nickname(self):
        self.assertTrue(assistant_routes._looks_like_unresolved_person_question("Расскажи про Сашку"))
        self.assertTrue(assistant_routes._looks_like_unresolved_person_question("расскажи про сашку"))

    def test_medical_subject_is_not_mistaken_for_a_person_name(self):
        self.assertFalse(assistant_routes._looks_like_unresolved_person_question("Расскажи про спастичности"))
        self.assertFalse(assistant_routes._looks_like_unresolved_person_question("Расскажи про анализы"))

    def test_singular_target_is_distinguished_from_multiple_people(self):
        self.assertTrue(assistant_routes._looks_like_single_patient_reference("Расскажи про Сашку"))
        self.assertFalse(assistant_routes._looks_like_single_patient_reference("Расскажи про Сашку и Олега"))
        self.assertFalse(assistant_routes._looks_like_single_patient_reference("Сравни Сашку и Олега"))

    def test_high_confidence_match_returns_only_registered_candidate(self):
        raw = '{"decision":"match","candidate_indices":[0],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, ["Александр Иванов"])
        self.assertEqual(status, "matched")

    def test_resolver_payload_contains_no_database_ids_or_medical_profile(self):
        raw = '{"decision":"match","candidate_indices":[0],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw) as model_call:
            assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        messages = model_call.call_args.args[0]
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["candidate_patients"][0]["name"], "Александр Иванов")
        self.assertEqual(payload["candidate_patients"][0]["aliases"], ["Саша", "Сашка"])
        self.assertNotIn("id", payload["candidate_patients"][0])
        self.assertNotIn("birth_date", payload["candidate_patients"][0])
        self.assertNotIn("medical_documents", payload)

    def test_low_confidence_match_fails_closed(self):
        raw = '{"decision":"match","candidate_indices":[0],"confidence":"medium"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, [])
        self.assertEqual(status, "ambiguous")

    def test_singular_query_cannot_expand_to_multiple_candidates(self):
        raw = '{"decision":"match","candidate_indices":[0,1],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, [])
        self.assertEqual(status, "ambiguous")

    def test_explicit_multi_patient_query_can_resolve_multiple_registered_candidates(self):
        raw = '{"decision":"match","candidate_indices":[0,1],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку и Олега", self.records)
        self.assertEqual(names, ["Александр Иванов", "Олег Петров"])
        self.assertEqual(status, "matched")

    def test_out_of_range_index_is_rejected(self):
        raw = '{"decision":"match","candidate_indices":[42],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, [])
        self.assertEqual(status, "invalid_output")

    def test_boolean_is_not_accepted_as_candidate_index(self):
        raw = '{"decision":"match","candidate_indices":[true],"confidence":"high"}'
        with patch.object(assistant_routes, "chat_completion", return_value=raw):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, [])
        self.assertEqual(status, "invalid_output")

    def test_malformed_output_fails_closed(self):
        with patch.object(assistant_routes, "chat_completion", return_value="не JSON"):
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", self.records)
        self.assertEqual(names, [])
        self.assertEqual(status, "invalid_output")

    def test_empty_registry_does_not_call_model(self):
        with patch.object(assistant_routes, "chat_completion") as model_call:
            names, status = assistant_routes._resolve_patient_reference_with_ai("Расскажи про Сашку", [])
        self.assertEqual(names, [])
        self.assertEqual(status, "no_candidates")
        model_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
