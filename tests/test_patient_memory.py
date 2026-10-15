import json
import os
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

_TMP = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = str(Path(_TMP.name) / "memory-test.sqlite3")
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

import tenancy
tenancy.DB_PATH = Path(os.environ["DB_PATH"])
tenancy.FERNET_KEY = os.environ["FERNET_KEY"]
import database as db
import patient_memory


class PatientMemoryTests(unittest.TestCase):
    def setUp(self):
        tenancy.init()
        db.init()
        self.family = tenancy.create_family("Test family", 1001)
        self.patient = "Иван Тестовый"
        db.add_patient(self.family, self.patient, birth_date="2020-01-01")
        self.doc_id = 0
        self._add_document(
            "Анализ крови",
            "лабораторный отчёт",
            "2026-04-10",
            {
                "lab_results": [
                    {"name": "Гемоглобин", "value": "115", "unit": "г/л", "page": 1, "source": "Гемоглобин 115 г/л"}
                ],
                "diagnoses": [{"text": "Железодефицитная анемия?", "page": 1}],
                "medications": [{"text": "Препарат железа — назначение в документе", "page": 1}],
            },
        )

    def _add_document(self, name, kind, doc_date, analysis):
        digest = f"{self.family}-{name}-{doc_date}"
        db.add_doc(
            self.family, self.patient, name, kind, doc_date,
            "local://test", "local://ocr", "Тестовый OCR",
            ["тест"], digest, analysis=analysis,
        )
        rows = db.search(self.family, self.patient, "", limit=1000)
        self.doc_id = next(row["id"] for row in rows if row["name"] == name)

    def test_memory_is_persisted_encrypted_and_source_linked(self):
        snapshot = patient_memory.refresh(self.family, self.patient)
        self.assertEqual(snapshot["document_count"], 1)
        self.assertEqual(snapshot["profile"]["birth_date"], "2020-01-01")
        self.assertEqual(snapshot["lab_results"][0]["value"], "115")
        self.assertEqual(snapshot["lab_results"][0]["source"]["document_id"], self.doc_id)
        self.assertEqual(snapshot["diagnoses_mentioned"][0]["evidence_type"], "mentioned_in_document")
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_enc,source_ids_enc FROM patient_memory_snapshots WHERE family_id=?",
                (self.family,),
            ).fetchone()
        self.assertNotIn("Гемоглобин", bytes(row["snapshot_enc"]).decode("latin1"))
        self.assertNotIn("115", bytes(row["snapshot_enc"]).decode("latin1"))
        self.assertEqual(json.loads(tenancy.cipher().decrypt(row["source_ids_enc"])), [self.doc_id])

    def test_memory_refreshes_when_new_document_is_added(self):
        first = patient_memory.refresh(self.family, self.patient)
        self._add_document(
            "УЗИ",
            "заключение УЗИ",
            "2026-05-02",
            {"diagnoses": [{"text": "Упоминание из заключения", "page": 2}]},
        )
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_enc FROM patient_memory_snapshots WHERE family_id=?",
                (self.family,),
            ).fetchone()
        automatically_updated = json.loads(tenancy.cipher().decrypt(row["snapshot_enc"]).decode("utf-8"))
        self.assertEqual(automatically_updated["document_count"], 2)
        self.assertEqual(automatically_updated["documents"][0]["name"], "УЗИ")
        second = patient_memory.refresh(self.family, self.patient)
        self.assertEqual(first["document_count"], 1)
        self.assertEqual(second["document_count"], 2)
        self.assertEqual(second["documents"][0]["name"], "УЗИ")

    def test_memory_is_scoped_to_family_and_patient(self):
        other_family = tenancy.create_family("Other family", 1002)
        db.add_patient(other_family, self.patient)
        snapshot = patient_memory.refresh(other_family, self.patient)
        self.assertEqual(snapshot["document_count"], 0)
        self.assertEqual(snapshot["lab_results"], [])

    def test_numeric_lab_trend_uses_matching_units_and_source_dates(self):
        self._add_document(
            "Повторный анализ крови",
            "лабораторный отчёт",
            "2026-05-10",
            {
                "lab_results": [
                    {"name": "Гемоглобин", "value": "120", "unit": "г/л", "page": 1, "source": "Гемоглобин 120 г/л"}
                ]
            },
        )
        snapshot = patient_memory.refresh(self.family, self.patient)
        trend = next(item for item in snapshot["lab_trends"] if item["name"] == "Гемоглобин")
        self.assertEqual(trend["previous"]["value"], "115")
        self.assertEqual(trend["latest"]["value"], "120")
        self.assertEqual(trend["absolute_change"], "5")
        self.assertEqual(trend["direction"], "increase")
        self.assertNotEqual(trend["latest"]["source"]["document_id"], trend["previous"]["source"]["document_id"])

    def test_lab_trends_do_not_mix_units_or_qualitative_results(self):
        self._add_document(
            "Другой анализ",
            "лабораторный отчёт",
            "2026-05-10",
            {
                "lab_results": [
                    {"name": "Гемоглобин", "value": "12", "unit": "g/dL", "page": 1, "source": "Hemoglobin 12 g/dL"},
                    {"name": "Ферритин", "value": "<5", "unit": "мкг/л", "page": 1, "source": "Ферритин <5 мкг/л"},
                ]
            },
        )
        snapshot = patient_memory.refresh(self.family, self.patient)
        self.assertEqual(snapshot["lab_trends"], [])

    def test_user_correction_is_encrypted_persistent_and_used_in_context(self):
        snapshot = patient_memory.get_snapshot(self.family, self.patient)
        original = snapshot["diagnoses_mentioned"][0]
        patient_memory.save_edit(
            self.family, self.patient, original["fact_key"], "correct",
            "Подтверждённое пользователем описание", note="Сверено с оригиналом",
        )
        corrected = patient_memory.get_snapshot(self.family, self.patient)["diagnoses_mentioned"][0]
        self.assertEqual(corrected["text"], "Подтверждённое пользователем описание")
        self.assertEqual(corrected["original_text"], original["text"])
        self.assertTrue(corrected["user_corrected"])
        self.assertEqual(corrected["correction_note"], "Сверено с оригиналом")
        self.assertEqual(corrected["source"]["document_id"], self.doc_id)
        context = patient_memory.to_context(patient_memory.get_snapshot(self.family, self.patient))
        self.assertIn("Подтверждённое пользователем описание", context)
        self.assertNotIn("- " + original["date"] + ": " + original["text"], context)
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT payload_enc FROM patient_memory_edits WHERE family_id=?",
                (self.family,),
            ).fetchone()
        self.assertNotIn("Подтверждённое пользователем описание", bytes(row["payload_enc"]).decode("latin1"))

    def test_user_can_hide_and_restore_a_memory_fact(self):
        snapshot = patient_memory.get_snapshot(self.family, self.patient)
        item = snapshot["medications_mentioned"][0]
        patient_memory.save_edit(self.family, self.patient, item["fact_key"], "ignore")
        self.assertEqual(patient_memory.get_snapshot(self.family, self.patient)["medications_mentioned"], [])
        patient_memory.save_edit(self.family, self.patient, item["fact_key"], "restore")
        self.assertEqual(
            patient_memory.get_snapshot(self.family, self.patient)["medications_mentioned"][0]["text"],
            item["text"],
        )

    def test_memory_edit_cannot_target_another_patient_fact(self):
        snapshot = patient_memory.get_snapshot(self.family, self.patient)
        fact_key = snapshot["diagnoses_mentioned"][0]["fact_key"]
        other_family = tenancy.create_family("Other family", 1003)
        db.add_patient(other_family, self.patient)
        with self.assertRaises(ValueError):
            patient_memory.save_edit(other_family, self.patient, fact_key, "ignore")

    def test_document_insert_and_reclassification_refresh_persisted_memory(self):
        # add_doc triggers a best-effort rebuild without an explicit memory-page request.
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_enc FROM patient_memory_snapshots WHERE family_id=?",
                (self.family,),
            ).fetchone()
        stored = json.loads(tenancy.cipher().decrypt(row["snapshot_enc"]).decode("utf-8"))
        self.assertEqual(stored["document_count"], 1)
        analysis = {
            "diagnoses": [{"text": "Ручная классификация обновлена", "page": 1}],
            "lab_results": [],
            "medications": [],
        }
        self.assertTrue(db.update_doc_metadata(self.family, self.doc_id, "заключение", "2026-04-11", analysis))
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_enc FROM patient_memory_snapshots WHERE family_id=?",
                (self.family,),
            ).fetchone()
        stored = json.loads(tenancy.cipher().decrypt(row["snapshot_enc"]).decode("utf-8"))
        self.assertEqual(stored["documents"][0]["kind"], "заключение")
        self.assertEqual(stored["diagnoses_mentioned"][0]["text"], "Ручная классификация обновлена")

    def test_context_has_caveats_and_source_ids(self):
        snapshot = patient_memory.refresh(self.family, self.patient)
        context = patient_memory.to_context(snapshot)
        self.assertIn("источник ID", context)
        self.assertIn("не считать диагнозы независимо подтверждёнными", context)
        self.assertIn("Гемоглобин = 115 г/л", context)


if __name__ == "__main__":
    unittest.main()
