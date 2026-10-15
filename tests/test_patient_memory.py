import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
import tenancy

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


    @patch("patient_memory.save_fact", return_value=17)
    @patch("ai_provider.chat_completion")
    def test_extraction_requires_verbatim_support_and_uses_application_date(self, completion, save):
        completion.return_value = (
            '{"facts":[{"category":"pregnancy","key":"Беременность",'
            '"value":"Сообщена пользователем","status":"user_reported",'
            '"source_type":"conversation","source_ref":"Сообщение пользователя",'
            '"observed_at":"2099-01-01","valid_until":"2099-12-31",'
            '"confidence":1.0,"exact_support":"Юля беременна"}]}'
        )
        ids = patient_memory.extract_and_save_facts(1, "Юля", "Юля беременна", [])
        self.assertEqual(ids, [17])
        saved_fact = save.call_args.args[2]
        self.assertEqual(saved_fact["observed_at"], patient_memory.date.today().isoformat())
        self.assertEqual(saved_fact["valid_until"], "")
        self.assertLessEqual(saved_fact["confidence"], 0.85)

    @patch("ai_provider.chat_completion")
    def test_question_is_not_automatically_saved_as_patient_fact(self, completion):
        result = patient_memory.extract_and_save_facts(1, "Юля", "Юля беременна?", [])
        self.assertEqual(result, [])
        completion.assert_not_called()


    def test_saved_memory_is_encrypted_and_scoped_to_family_and_patient(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.sqlite3"
            with patch.object(tenancy, "DB_PATH", db_path), patch.object(
                tenancy, "FERNET_KEY", Fernet.generate_key().decode("ascii")
            ):
                with tenancy.connect() as conn:
                    conn.execute(
                        "CREATE TABLE families(id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_telegram_id INTEGER NOT NULL)"
                    )
                    conn.execute("INSERT INTO families(id,name,owner_telegram_id) VALUES(1,'Family',1)")
                    conn.execute("INSERT INTO families(id,name,owner_telegram_id) VALUES(2,'Other',2)")
                fact_id = patient_memory.save_fact(1, "Юля", {
                    "category": "pregnancy", "key": "Беременность",
                    "value": "Сообщена пользователем", "status": "user_reported",
                    "source_type": "conversation", "source_ref": "Сообщение пользователя",
                })
                facts = patient_memory.list_facts(1, "Юля")
                self.assertEqual([f["id"] for f in facts], [fact_id])
                self.assertEqual(patient_memory.list_facts(2, "Юля"), [])
                with sqlite3.connect(db_path) as conn:
                    row = conn.execute(
                        "SELECT category,fact_key,payload_enc,source_ref FROM patient_memory_facts WHERE id=?",
                        (fact_id,),
                    ).fetchone()
                self.assertEqual(row[0], "other")
                self.assertIsNone(row[3])
                self.assertNotIn(b"Беременность", row[2])
                self.assertNotIn(b"Сообщена пользователем", row[2])


if __name__ == "__main__":
    unittest.main()
