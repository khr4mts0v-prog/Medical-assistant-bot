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

    def test_manual_facts_are_encrypted_audited_and_in_assistant_context(self):
        fact_id = patient_memory.add_manual_fact(
            self.family, self.patient, "Со слов пациента, препарат отменён",
            "medication", "12.10.2026", 1001,
        )
        facts = patient_memory.get_manual_facts(self.family, self.patient)
        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["id"], fact_id)
        self.assertEqual(fact["origin"], "user_entered")
        self.assertIsNone(fact["source"])
        self.assertEqual(fact["created_by"], 1001)
        with tenancy.connect() as conn:
            row = conn.execute(
                "SELECT payload_enc FROM patient_memory_manual_facts WHERE id=?", (fact_id,)
            ).fetchone()
        self.assertNotIn("препарат отменён", bytes(row["payload_enc"]).decode("latin1"))
        snapshot = patient_memory.get_snapshot(self.family, self.patient)
        context = patient_memory.to_context(snapshot)
        self.assertIn("РУЧНЫЕ ЗАПИСИ ПОЛЬЗОВАТЕЛЯ", context)
        self.assertIn("документ-источник отсутствует", context)
        self.assertIn("препарат отменён", context)

    def test_manual_facts_can_be_updated_and_deleted_with_patient_isolation(self):
        fact_id = patient_memory.add_manual_fact(
            self.family, self.patient, "Первоначальная заметка", "note", "", 1001,
        )
        patient_memory.update_manual_fact(
            self.family, self.patient, fact_id, "Исправленная заметка", "symptom", "2026-10-12", 1001,
        )
        fact = patient_memory.get_manual_facts(self.family, self.patient)[0]
        self.assertEqual(fact["text"], "Исправленная заметка")
        self.assertEqual(fact["category"], "symptom")
        self.assertEqual(fact["date"], "2026-10-12")
        other_family = tenancy.create_family("Другой архив", 1002)
        db.add_patient(other_family, self.patient)
        with self.assertRaises(ValueError):
            patient_memory.update_manual_fact(other_family, self.patient, fact_id, "Чужая запись", "note", "", 1002)
        with self.assertRaises(ValueError):
            patient_memory.delete_manual_fact(other_family, self.patient, fact_id)
        patient_memory.delete_manual_fact(self.family, self.patient, fact_id)
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient), [])

    def test_manual_fact_rejects_invalid_date_and_empty_text(self):
        with self.assertRaises(ValueError):
            patient_memory.add_manual_fact(self.family, self.patient, "Запись", "note", "вчера", 1001)
        with self.assertRaises(ValueError):
            patient_memory.add_manual_fact(self.family, self.patient, "   ", "note", "", 1001)

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
        encrypted_snapshot = bytes(row["snapshot_enc"])
        decrypted_snapshot = json.loads(tenancy.cipher().decrypt(encrypted_snapshot).decode("utf-8"))
        self.assertEqual(decrypted_snapshot["lab_results"][0]["value"], "115")
        self.assertNotEqual(encrypted_snapshot, json.dumps(decrypted_snapshot, ensure_ascii=False).encode("utf-8"))
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

    def test_deleting_source_document_removes_its_memory_correction(self):
        snapshot = patient_memory.get_snapshot(self.family, self.patient)
        item = snapshot["diagnoses_mentioned"][0]
        patient_memory.save_edit(self.family, self.patient, item["fact_key"], "correct", "Исправленный факт")
        self.assertTrue(db.delete_doc(self.family, self.doc_id))
        with tenancy.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM patient_memory_edits WHERE family_id=?",
                (self.family,),
            ).fetchone()["n"]
        self.assertEqual(count, 0)
        self.assertEqual(patient_memory.get_snapshot(self.family, self.patient)["document_count"], 0)

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

    def test_memory_suggestion_requires_explicit_acceptance_and_supersedes_old_measurement(self):
        first = patient_memory.propose_fact(
            self.family, self.patient, "Вес: около 15 кг", "note", "2026-10-16",
            memory_key="weight_kg", reason="Сообщено пользователем", actor_id=1001,
        )
        self.assertEqual(first["status"], "pending")
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient), [])
        self.assertIn(first["id"], [item["id"] for item in patient_memory.get_snapshot(self.family, self.patient)["pending_proposals"]])
        with tenancy.connect() as conn:
            stored = conn.execute(
                "SELECT payload_enc FROM patient_memory_proposals WHERE id=?", (first["id"],)
            ).fetchone()
        self.assertNotIn("около 15 кг", bytes(stored["payload_enc"]).decode("latin1"))

        first_fact_id = patient_memory.accept_proposal(self.family, self.patient, first["id"], 1001)
        active = patient_memory.get_manual_facts(self.family, self.patient)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], first_fact_id)
        self.assertEqual(active[0]["memory_key"], "weight_kg")
        self.assertEqual(active[0]["origin"], "approved_conversation")

        second = patient_memory.propose_fact(
            self.family, self.patient, "Вес: 16 кг", "note", "2026-10-16",
            memory_key="weight_kg", reason="Новое значение от пользователя", actor_id=1001,
        )
        self.assertIn("Вес: около 15 кг", second["reason"])
        self.assertIn("останется в истории", second["reason"])
        second_fact_id = patient_memory.accept_proposal(self.family, self.patient, second["id"], 1001)
        all_facts = patient_memory.get_manual_facts(self.family, self.patient, include_inactive=True)
        by_id = {item["id"]: item for item in all_facts}
        self.assertEqual(by_id[first_fact_id]["status"], "inactive")
        self.assertEqual(by_id[second_fact_id]["status"], "active")
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient)[0]["text"], "Вес: 16 кг")

    def test_fresh_identical_measurement_does_not_need_an_update_proposal(self):
        patient_memory.add_manual_fact(
            self.family, self.patient, "Вес: 15 кг", "note", "2026-10-16", 1001,
            memory_key="weight_kg",
        )
        self.assertFalse(patient_memory.should_propose_measurement(
            self.family, self.patient, "weight_kg", "Вес: около 15 кг"
        ))
        self.assertTrue(patient_memory.should_propose_measurement(
            self.family, self.patient, "weight_kg", "Вес: около 16 кг"
        ))

    def test_stale_identical_measurement_can_be_proposed_for_confirmation(self):
        patient_memory.add_manual_fact(
            self.family, self.patient, "Вес: 15 кг", "note", "2025-01-01", 1001,
            memory_key="weight_kg",
        )
        self.assertTrue(patient_memory.should_propose_measurement(
            self.family, self.patient, "weight_kg", "Вес: около 15 кг"
        ))

    def test_document_memory_suggestion_keeps_source_and_is_not_active_before_acceptance(self):
        rows = db.search(self.family, self.patient, "", limit=1000)
        source = next(row for row in rows if row["name"] == "Анализ крови")
        proposal = patient_memory.propose_fact(
            self.family, self.patient, "Основное состояние, указанное в заключении", "diagnosis", "2026-04-10",
            memory_key="diagnosis", reason="Потенциально важный долговременный факт",
            source={"document_id": source["id"], "name": source["name"], "date": source["date"], "kind": source["kind"]},
            actor_id=1001,
        )
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient), [])
        patient_memory.accept_proposal(self.family, self.patient, proposal["id"], 1001)
        fact = next(item for item in patient_memory.get_manual_facts(self.family, self.patient) if item["text"] == "Основное состояние, указанное в заключении")
        self.assertEqual(fact["origin"], "approved_document")
        self.assertEqual(fact["source"]["document_id"], source["id"])
        self.assertIn("Основное состояние, указанное в заключении", patient_memory.to_context(patient_memory.get_snapshot(self.family, self.patient)))

    def test_context_has_caveats_and_source_ids(self):
        snapshot = patient_memory.refresh(self.family, self.patient)
        context = patient_memory.to_context(snapshot)
        self.assertIn("источник ID", context)
        self.assertIn("не считать диагнозы независимо подтверждёнными", context)
        self.assertIn("Гемоглобин = 115 г/л", context)


    def test_proposal_acceptance_flows_into_next_context_only_for_target_patient(self):
        other_patient = "Мария Тестовая"
        db.add_patient(self.family, other_patient, birth_date="2022-02-02")
        rows = db.search(self.family, self.patient, "", limit=1000)
        source_row = next(row for row in rows if row["name"] == "Анализ крови")
        proposal_text = "Со слов пользователя: длительный приём препарата X"

        proposal = patient_memory.propose_fact(
            self.family, self.patient, proposal_text, "medication", "2026-10-20",
            memory_key="medication", reason="Проверить и подтвердить перед сохранением",
            source={"document_id": source_row["id"], "name": source_row["name"],
                    "date": source_row["date"], "kind": source_row["kind"]},
            actor_id=1001,
        )
        before = patient_memory.get_snapshot(self.family, self.patient)
        self.assertIn(proposal["id"], [item["id"] for item in before["pending_proposals"]])
        self.assertNotIn(proposal_text, patient_memory.to_context(before))
        self.assertNotIn(proposal_text, patient_memory.to_context(
            patient_memory.get_snapshot(self.family, other_patient)
        ))
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient), [])

        fact_id = patient_memory.accept_proposal(self.family, self.patient, proposal["id"], 1001)
        next_snapshot = patient_memory.get_snapshot(self.family, self.patient)
        next_context = patient_memory.to_context(next_snapshot)
        confirmed = next(item for item in patient_memory.get_manual_facts(self.family, self.patient)
                         if item["id"] == fact_id)
        self.assertEqual(confirmed["status"], "active")
        self.assertEqual(confirmed["origin"], "approved_document")
        self.assertEqual(confirmed["source"]["document_id"], source_row["id"])
        self.assertIn(proposal_text, next_context)
        self.assertIn("документ ID " + str(source_row["id"]), next_context)
        self.assertNotIn(proposal_text, patient_memory.to_context(
            patient_memory.get_snapshot(self.family, other_patient)
        ))
        with self.assertRaises(ValueError):
            patient_memory.accept_proposal(self.family, other_patient, proposal["id"], 1001)
        with self.assertRaises(ValueError):
            patient_memory.accept_proposal(self.family, self.patient, proposal["id"], 1001)

    def test_rejected_proposal_never_enters_confirmed_context(self):
        proposal_text = "Пользователь сомневается в актуальности препарата Y"
        proposal = patient_memory.propose_fact(
            self.family, self.patient, proposal_text, "medication", "2026-10-20",
            memory_key="medication", reason="Требуется подтверждение",
            actor_id=1001,
        )
        patient_memory.reject_proposal(self.family, self.patient, proposal["id"])
        self.assertEqual(patient_memory.get_manual_facts(self.family, self.patient), [])
        self.assertNotIn(proposal_text, patient_memory.to_context(
            patient_memory.get_snapshot(self.family, self.patient)
        ))
        closed = patient_memory.get_proposals(self.family, self.patient, include_closed=True)
        rejected = next(item for item in closed if item["id"] == proposal["id"])
        self.assertEqual(rejected["status"], "rejected")
        with self.assertRaises(ValueError):
            patient_memory.accept_proposal(self.family, self.patient, proposal["id"], 1001)


if __name__ == "__main__":
    unittest.main()
