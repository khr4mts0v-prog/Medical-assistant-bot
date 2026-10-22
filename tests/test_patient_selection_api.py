import os
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")

import webapp
import assistant_routes
from fastapi.testclient import TestClient


class TestPatientSelectionApi:
    def setup_method(self):
        self.client = TestClient(webapp.app)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123456
        self.oleg_cbc = {"id": 10, "patient": "Олег", "name": "ОАК.pdf", "kind": "анализ крови", "date": "01-10-2026", "text": "SELECTED_OLEG_CBC", "analysis": {}, "keywords": []}
        self.oleg_us = {"id": 11, "patient": "Олег", "name": "УЗИ.pdf", "kind": "УЗИ", "date": "02-10-2026", "text": "SELECTED_OLEG_US", "analysis": {}, "keywords": []}
        self.sasha_mri = {"id": 20, "patient": "Саша", "name": "МРТ.pdf", "kind": "МРТ", "date": "03-10-2026", "text": "SASHA_MRI_MUST_NOT_LEAK", "analysis": {}, "keywords": []}
        self.patches = [
            patch("tenancy.families_for_user", return_value=[{"id": 1}]),
            patch("tenancy.role_for_user", return_value="owner"),
            patch("tenancy.get_family", return_value={"id": 1}),
            patch("tenancy.is_demo_family", return_value=False),
            patch("database.patients", return_value=["Олег", "Саша"]),
            patch("database.patient_records", return_value=[{"name": "Олег", "aliases": ["Олег"]}, {"name": "Саша", "aliases": ["Саша"]}]),
            patch("ai_consent.get", return_value={"granted": True}),
            patch("assistant_routes.provider_config", return_value=("test", "test-token", "https://example.invalid", "test-model", "test-key")),
            patch("ai_trace_log.start", return_value="test-trace"),
            patch("ai_trace_log.emit"),
            patch("ai_trace_log.emit_full"),
            patch("ai_interaction_log.record"),
            patch("patient_memory.get_snapshot", return_value={"patient": "Олег"}),
            patch("patient_memory.to_context", return_value="MEMORY_OLEG_ONLY"),
            patch("patient_memory.get_proposals", return_value=[]),
        ]
        for item in self.patches:
            item.start()

    def teardown_method(self):
        for item in reversed(self.patches):
            item.stop()
        webapp.app.dependency_overrides.pop(webapp.current_user, None)

    def test_conversational_measurements_return_confirmation_proposals_without_calling_model(self):
        proposals = [
            {"id": 101, "text": "Рост: 170 см", "memory_key": "height_cm", "reason": "Со слов пользователя"},
            {"id": 102, "text": "Вес: около 97 кг", "memory_key": "weight_kg", "reason": "Со слов пользователя"},
        ]
        with patch("patient_memory.should_propose_measurement", return_value=True), \
             patch("patient_memory.propose_fact", side_effect=proposals) as propose, \
             patch("assistant_routes.chat_completion") as completion:
            response = self.client.post("/api/intelligent-search", json={
                "query": "Мой рост 170 см, вешу примерно 97 кг", "family_id": 1,
                "patient_scope": "Олег", "document_selection_mode": False,
                "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["mode"] == "memory_update"
        assert payload["memory_proposals"] == proposals
        assert "подтверди сохранение" in payload["answer"]
        assert propose.call_count == 2
        completion.assert_not_called()

    def test_unscoped_conversational_measurements_ask_which_patient(self):
        with patch("patient_memory.propose_fact") as propose, \
             patch("assistant_routes.chat_completion") as completion:
            response = self.client.post("/api/intelligent-search", json={
                "query": "Мой рост 170 см, вешу примерно 97 кг", "family_id": 1,
                "document_selection_mode": False, "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["mode"] == "memory_clarification"
        assert "для кого" in payload["answer"]
        assert payload["memory_proposals"] == []
        propose.assert_not_called()
        completion.assert_not_called()

    def test_memory_proposal_accept_action_calls_confirmation_handler(self):
        with \
             patch("patient_memory.accept_proposal", return_value=777) as accept:
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 1, "patient": "Олег", "proposal_id": 101, "action": "accept",
            })
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "status": "accepted", "fact_id": 777}
        accept.assert_called_once_with(1, "Олег", 101, 123456)

    def test_memory_proposal_reject_action_calls_rejection_handler(self):
        with \
             patch("patient_memory.reject_proposal") as reject:
            response = self.client.post("/api/patient-memory/proposal-action", json={
                "family_id": 1, "patient": "Олег", "proposal_id": 101, "action": "reject",
            })
        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True, "status": "rejected"}
        reject.assert_called_once_with(1, "Олег", 101)

    def test_unknown_person_lookup_is_answered_locally_without_calling_model(self):
        with patch("assistant_routes.chat_completion") as completion, \
             patch("assistant_routes._planner") as planner, \
             patch("assistant_routes._retrieve") as retrieve:
            response = self.client.post("/api/intelligent-search", json={
                "query": "Что можешь рассказать о Марии?", "family_id": 1,
                "document_selection_mode": False, "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["documents"] == []
        assert "не могу подтверждать или опровергать" in payload["answer"]
        assert "Мария — член семьи" not in payload["answer"]
        completion.assert_not_called()
        planner.assert_not_called()
        retrieve.assert_not_called()

    def test_selected_mode_sends_only_selected_sources_and_scoped_memory(self):
        with patch("database.get_documents_by_ids", return_value=[self.oleg_cbc, self.oleg_us]) as fetch, \
             patch("database.search") as search, \
             patch("assistant_routes._search_referenced_documents") as second_pass, \
             patch("assistant_routes._structured_archive_answer", wraps=assistant_routes._structured_archive_answer) as answer:
            # Replace the wrapped call's network dependency so the test stays offline.
            with patch("assistant_routes.chat_completion", return_value='{"answer":"Проверенный ответ","missing_documents":[],"limitations":[],"data_completeness":"partial","memory_updates":[]}'):
                response = self.client.post("/api/intelligent-search", json={
                    "query": "Сравни анализы Саши", "family_id": 1, "patient_scope": "Олег",
                    "document_selection_mode": True, "selected_document_ids": [10, 11], "consent": False,
                    "conversation": [{"question": "Что у Саши?", "answer": "SASHA_PRIOR_ANSWER_MUST_NOT_LEAK"}],
                })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [doc["id"] for doc in payload["documents"]] == [10, 11]
        assert all(doc["patient"] == "Олег" for doc in payload["documents"])
        fetch.assert_called_once_with(1, "Олег", [10, 11])
        search.assert_not_called()
        second_pass.assert_not_called()
        args, kwargs = answer.call_args
        assert args[1] == ["Олег"]
        assert args[2] == [self.oleg_cbc, self.oleg_us]
        assert args[3] == []  # no prior answer/history is passed in selected-document mode
        assert "Пациент: Олег" in kwargs["memory_context"]
        assert "MEMORY_OLEG_ONLY" in kwargs["memory_context"]
        assert "Саша" not in kwargs["memory_context"]

    def test_unscoped_family_summary_still_retrieves_multiple_patients(self):
        family_rows = [self.oleg_cbc, self.sasha_mri]
        with patch("assistant_routes._planner", return_value={"search_terms": [], "document_types": [], "allow_full_history": True}), \
             patch("assistant_routes._retrieve", side_effect=lambda fid, person, plan, result_limit=None: [row for row in family_rows if row["patient"] == person]), \
             patch("assistant_routes._structured_archive_answer", wraps=assistant_routes._structured_archive_answer) as answer, \
             patch("assistant_routes.chat_completion", return_value='{"answer":"Семейная сводка","missing_documents":[],"limitations":[],"data_completeness":"partial","memory_updates":[]}'):
            response = self.client.post("/api/intelligent-search", json={
                "query": "Сделай сводку по всем пациентам", "family_id": 1,
                "document_selection_mode": False, "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        assert {doc["patient"] for doc in response.json()["documents"]} == {"Олег", "Саша"}
        assert answer.call_args.args[1] == ["Олег", "Саша"]
        assert {row["patient"] for row in answer.call_args.args[2]} == {"Олег", "Саша"}

    def test_duplicate_custom_alias_requires_patient_clarification(self):
        with patch("database.patient_records", return_value=[
            {"name": "Дмитрий Иванов", "aliases": ["Дмитрий Иванов", "Димка"]},
            {"name": "Денис Петров", "aliases": ["Денис Петров", "Димка"]},
        ]), patch("assistant_routes.chat_completion") as completion, \
             patch("assistant_routes._planner") as planner, \
             patch("assistant_routes._retrieve") as retrieve:
            response = self.client.post("/api/intelligent-search", json={
                "query": "Сравни документы Димка", "family_id": 1,
                "document_selection_mode": False, "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "псевдоним назначен нескольким пациентам" in payload["answer"]
        assert payload["documents"] == []
        completion.assert_not_called()
        planner.assert_not_called()
        retrieve.assert_not_called()

    def test_duplicate_custom_alias_with_unique_surname_retrieves_only_that_patient(self):
        with patch("database.patient_records", return_value=[
            {"name": "Дмитрий Иванов", "aliases": ["Дмитрий Иванов", "Димка"]},
            {"name": "Денис Петров", "aliases": ["Денис Петров", "Димка"]},
        ]), patch("assistant_routes._planner", return_value={"search_terms": [], "document_types": [], "allow_full_history": False}), \
             patch("assistant_routes._retrieve", side_effect=lambda fid, person, plan, result_limit=15: [
                 self.oleg_cbc if person == "Дмитрий Иванов" else self.oleg_us
             ] if person == "Дмитрий Иванов" else []), \
             patch("assistant_routes._structured_archive_answer", return_value={
                 "answer":"Ответ", "missing_documents":[], "limitations":[],
                 "data_completeness":"partial", "memory_updates":[],
             }) as answer:
            # Configure the database roster names to match the two candidate aliases.
            with patch("database.patients", return_value=["Дмитрий Иванов", "Денис Петров"]):
                response = self.client.post("/api/intelligent-search", json={
                    "query": "Сравни документы Димка Иванов", "family_id": 1,
                    "document_selection_mode": False, "selected_document_ids": [], "consent": False,
                })
        assert response.status_code == 200, response.text
        assert answer.call_args.args[1] == ["Дмитрий Иванов"]

    def test_selected_mode_rejects_document_from_another_patient(self):
        with patch("database.get_documents_by_ids", return_value=[self.sasha_mri]):
            response = self.client.post("/api/intelligent-search", json={
                "query": "Сравни документы", "family_id": 1, "patient_scope": "Олег",
                "document_selection_mode": True, "selected_document_ids": [20], "consent": False,
            })
        assert response.status_code == 400
        assert "не принадлежат выбранному пациенту" in response.json()["detail"]

    def test_selected_mode_rejects_non_integer_document_ids(self):
        response = self.client.post("/api/intelligent-search", json={
            "query": "Сравни документы", "family_id": 1, "patient_scope": "Олег",
            "document_selection_mode": True, "selected_document_ids": [10.5], "consent": False,
        })
        assert response.status_code == 400
        assert "Некорректный список" in response.json()["detail"]

    def test_selected_mode_rejects_empty_and_over_limit_selection_before_ai(self):
        for selected_ids, expected in [([], "Отметьте хотя бы один"), (list(range(1, 42)), "не более 40")]:
            response = self.client.post("/api/intelligent-search", json={
                "query": "Сравни документы", "family_id": 1, "patient_scope": "Олег",
                "document_selection_mode": True, "selected_document_ids": selected_ids, "consent": False,
            })
            assert response.status_code == 400
            assert expected in response.json()["detail"]

    def test_family_comparison_uses_latest_requested_labs_for_each_patient(self):
        oleg_old = {"id": 12, "patient": "Олег", "name": "ОАК-old.pdf", "kind": "лабораторный отчёт", "date": "01.09.2026", "text": "OLDER_OLEG_CBC", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "130"}]}, "keywords": []}
        oleg_latest = {"id": 13, "patient": "Олег", "name": "ОАК-new.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "text": "LATEST_OLEG_CBC", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "140"}]}, "keywords": []}
        sasha_old = {"id": 21, "patient": "Саша", "name": "ОАК-old.pdf", "kind": "лабораторный отчёт", "date": "01.08.2026", "text": "OLDER_SASHA_CBC", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "105"}]}, "keywords": []}
        sasha_latest = {"id": 22, "patient": "Саша", "name": "ОАК-new.pdf", "kind": "лабораторный отчёт", "date": "09.10.2026", "text": "LATEST_SASHA_CBC", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "115"}]}, "keywords": []}
        rows = [oleg_old, oleg_latest, sasha_old, sasha_latest]
        def fake_retrieve(fid, patient, plan, result_limit=15):
            assert result_limit is None, "comparison must evaluate candidates before choosing latest per person"
            return [row for row in rows if row["patient"] == patient]
        with patch("assistant_routes._planner", return_value={"search_terms": [], "document_types": [], "allow_full_history": False}), \
             patch("assistant_routes._retrieve", side_effect=fake_retrieve) as retrieve, \
             patch("assistant_routes._search_referenced_documents") as second_pass, \
             patch("assistant_routes._structured_archive_answer", wraps=assistant_routes._structured_archive_answer) as answer, \
             patch("assistant_routes.chat_completion", return_value='{"answer":"Сравнение готово","missing_documents":[],"limitations":[],"data_completeness":"sufficient","memory_updates":[]}'):
            response = self.client.post("/api/intelligent-search", json={
                "query": "Сравни показатели крови Саши и Олега", "family_id": 1,
                "document_selection_mode": False, "selected_document_ids": [], "consent": False,
            })
        assert response.status_code == 200, response.text
        selected = answer.call_args.args[2]
        assert {row["id"] for row in selected} == {13, 22}
        assert {row["patient"] for row in selected} == {"Олег", "Саша"}
        assert "OLDER_OLEG_CBC" not in assistant_routes._context(selected)
        assert "OLDER_SASHA_CBC" not in assistant_routes._context(selected)
        assert retrieve.call_count == 2
        second_pass.assert_not_called()
        assert {doc["id"] for doc in response.json()["documents"]} == {13, 22}

    def test_patient_card_rejects_explicit_cross_patient_comparison(self):
        response = self.client.post("/api/intelligent-search", json={
            "query": "Сравни показатели крови Саши и Олега", "family_id": 1,
            "patient_scope": "Олег", "document_selection_mode": False,
            "selected_document_ids": [], "consent": False,
        })
        assert response.status_code == 400
        assert "общего семейного чата" in response.json()["error"]
