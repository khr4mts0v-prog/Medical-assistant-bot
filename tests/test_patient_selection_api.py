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