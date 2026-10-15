import unittest
from unittest.mock import patch

import patient_memory


class PatientMemoryValidationTests(unittest.TestCase):
    def test_valid_fact_keeps_source_and_status(self):
        fact = patient_memory._validate_fact({
            "category": "pregnancy", "key": "Беременность",
            "value": "Сообщена пользователем", "status": "user_reported",
            "source_type": "conversation", "observed_at": "2026-10-15",
        })
        self.assertEqual(fact["category"], "pregnancy")
        self.assertEqual(fact["status"], "user_reported")
        self.assertEqual(fact["observed_at"], "2026-10-15")

    def test_does_not_accept_unknown_category_or_status(self):
        with self.assertRaises(ValueError):
            patient_memory._validate_fact({"category": "diagnosis_guess", "key": "x", "value": "y"})
        with self.assertRaises(ValueError):
            patient_memory._validate_fact({
                "category": "condition", "key": "x", "value": "y", "status": "certainly_true"
            })

    def test_does_not_invent_or_accept_malformed_dates(self):
        with self.assertRaises(ValueError):
            patient_memory._validate_fact({
                "category": "measurement", "key": "Вес", "value": "70 кг",
                "observed_at": "вчера примерно",
            })

    def test_context_labels_sources_and_does_not_call_old_medication_current(self):
        facts = [
            {"id": 1, "category": "medication", "key": "Препарат", "value": "Назначен в выписке",
             "status": "documented", "source_type": "document", "source_ref": "Выписка от 2025-01-10",
             "observed_at": "2025-01-10", "valid_until": "", "confidence": 0.9, "notes": "Текущий приём не подтверждён"},
        ]
        with patch.object(patient_memory, "list_facts", return_value=facts):
            context = patient_memory.build_context(1, "Пациент", "лекарство")
        self.assertIn("статус=documented", context)
        self.assertIn("Текущий приём не подтверждён", context)
        self.assertIn("Не считай старое назначение доказательством текущего приёма", context)

    def test_expired_fact_is_not_in_current_context(self):
        facts = [
            {"id": 1, "category": "pregnancy", "key": "Беременность", "value": "Сообщено",
             "status": "user_reported", "source_type": "conversation", "source_ref": "",
             "observed_at": "2025-01-01", "valid_until": "2025-02-01", "confidence": 0.7, "notes": ""},
        ]
        with patch.object(patient_memory, "list_facts", return_value=facts):
            context = patient_memory.build_context(1, "Пациент", "лекарство")
        self.assertNotIn("Беременность", context)


if __name__ == "__main__":
    unittest.main()
