import unittest
from unittest.mock import patch

import assistant_routes as assistant


class AssistantChatGapTests(unittest.TestCase):
    def test_patient_card_scope_is_validated_and_cannot_resolve_to_another_family_member(self):
        self.assertEqual(assistant._resolve_patient_scope(["Олег", "Саша"], "Олег"), "Олег")
        self.assertEqual(assistant._resolve_patient_scope(["Олег", "Саша"], ""), "")
        with self.assertRaisesRegex(ValueError, "не найден"):
            assistant._resolve_patient_scope(["Олег", "Саша"], "Мария")

    def test_document_selection_mode_rejects_stale_ids_instead_of_silently_broadening_scope(self):
        assistant._validate_document_selection_mode(False, [], "")
        assistant._validate_document_selection_mode(True, [10], "Олег")
        with self.assertRaisesRegex(ValueError, "режим выбора выключен"):
            assistant._validate_document_selection_mode(False, [10], "Олег")
        with self.assertRaisesRegex(ValueError, "только из карточки пациента"):
            assistant._validate_document_selection_mode(True, [10], "")

    def test_selected_document_resolver_returns_only_requested_sources_in_selection_order(self):
        rows = [
            {"id": 10, "patient": "Олег", "name": "ОАК.pdf", "text": "Гемоглобин"},
            {"id": 11, "patient": "Олег", "name": "УЗИ.pdf", "text": "УЗИ сердца"},
            {"id": 12, "patient": "Саша", "name": "МРТ.pdf", "text": "МРТ головного мозга"},
        ]
        with patch("assistant_routes.db.get_documents_by_ids", return_value=rows) as fetch_by_ids, \
             patch("assistant_routes.db.search") as search:
            selected = assistant._selected_patient_documents(1, "Олег", [11, 10])
        self.assertEqual([row["id"] for row in selected], [11, 10])
        fetch_by_ids.assert_called_once_with(1, "Олег", [11, 10])
        search.assert_not_called()

    def test_selected_document_resolver_rejects_other_patients_and_unknown_ids(self):
        rows = [
            {"id": 10, "patient": "Олег", "name": "ОАК.pdf", "text": "Гемоглобин"},
            {"id": 12, "patient": "Саша", "name": "МРТ.pdf", "text": "МРТ головного мозга"},
        ]
        with patch("assistant_routes.db.get_documents_by_ids", return_value=rows):
            with self.assertRaisesRegex(ValueError, "не принадлежат выбранному пациенту"):
                assistant._selected_patient_documents(1, "Олег", [12])
            with self.assertRaisesRegex(ValueError, "не принадлежат выбранному пациенту"):
                assistant._selected_patient_documents(1, "Олег", [999])

    def test_selected_document_resolver_enforces_nonempty_and_maximum(self):
        with self.assertRaisesRegex(ValueError, "Отметьте хотя бы один"):
            assistant._selected_patient_documents(1, "Олег", [])
        with self.assertRaisesRegex(ValueError, "не более 40"):
            assistant._selected_patient_documents(1, "Олег", list(range(1, 42)))

    def test_selected_context_contains_only_selected_documents_and_patient_memory(self):
        selected = [
            {"id": 10, "patient": "Олег", "name": "ОАК.pdf", "kind": "анализ крови", "date": "01-10-2026", "text": "SELECTED_OLeg_CBC"},
            {"id": 11, "patient": "Олег", "name": "УЗИ.pdf", "kind": "УЗИ", "date": "02-10-2026", "text": "SELECTED_OLeg_US"},
        ]
        with patch("assistant_routes.chat_completion", return_value='{"answer":"Готово","missing_documents":[],"limitations":[],"data_completeness":"partial","memory_updates":[]}') as completion:
            assistant._structured_archive_answer("Сравни эти документы", ["Олег"], selected, [], memory_context="MEMORY_OLeg_ONLY")
        system_prompt = completion.call_args.args[0][0]["content"]
        user_prompt = completion.call_args.args[0][1]["content"]
        self.assertIn("разрешённую область анализа", system_prompt)
        self.assertIn("MEMORY_OLeg_ONLY", user_prompt)
        self.assertIn("SELECTED_OLeg_CBC", user_prompt)
        self.assertIn("SELECTED_OLeg_US", user_prompt)
        self.assertIn("естественное короткое имя", system_prompt)
        self.assertNotIn("UNSELECTED", user_prompt)
        self.assertNotIn("Саша", user_prompt)

    def test_selected_mode_never_runs_second_pass_reference_search(self):
        # The route's selection-mode branch is deliberately tested via the guard helper
        # that is used for referenced-document expansion: selected IDs stay the allow-list.
        with patch("assistant_routes.db.get_documents_by_ids", return_value=[
            {"id": 10, "patient": "Олег", "name": "ОАК.pdf", "text": "selected"},
        ]), patch("assistant_routes.db.search") as search:
            selected = assistant._selected_patient_documents(1, "Олег", [10])
            self.assertEqual([row["id"] for row in selected], [10])
            search.assert_not_called()

    def test_inflected_first_name_inside_full_name_resolves_registered_patient(self):
        people = [{"name": "Храмцов Олег Михайлович", "aliases": []}]
        self.assertEqual(
            assistant._mentioned_people(people, "Расскажи про Олега все что знаешь"),
            ["Храмцов Олег Михайлович"],
        )

    def test_everything_you_know_phrase_requests_full_archive_history(self):
        question = "Расскажи про Олега все что знаешь"
        self.assertTrue(assistant._explicit_full_history(question))
        plan = assistant._fallback_plan(question)
        self.assertTrue(plan["allow_full_history"])

    def test_summary_request_routes_to_analysis(self):
        self.assertTrue(assistant._needs_ai_analysis("Дай краткую сводку по УЗИ Саши"))

    def test_brief_summary_is_distinct_from_full_history_request(self):
        self.assertTrue(assistant._is_brief_summary_request("Дай краткую сводку по всем пациентам"))
        self.assertTrue(assistant._is_brief_summary_request("Сделай сводку по Олегу"))
        self.assertFalse(assistant._is_brief_summary_request("Дай краткую сводку по УЗИ Саши"))
        self.assertFalse(assistant._is_brief_summary_request("Краткая сводка по анализам крови Саши"))
        self.assertFalse(assistant._is_brief_summary_request("Сводка по анализам крови всех пациентов"))
        self.assertFalse(assistant._is_brief_summary_request("Найди результат колоноскопии"))
        self.assertFalse(assistant._explicit_full_history("Дай краткую сводку по всем пациентам"))

    def test_adding_omitted_study_keeps_prior_overall_summary_mode(self):
        previous = "Дай краткую сводку по всем пациентам"
        current = "Ты не взял в сводку результат колоноскопии"
        combined = "Предыдущий вопрос: " + previous + "\nТекущее уточнение пользователя: " + current
        self.assertFalse(assistant._is_brief_summary_request(combined))
        self.assertTrue(assistant._should_rebuild_brief_summary(
            combined, previous_question=previous, followup=True, explicit_document_addition=True
        ))
        self.assertFalse(assistant._should_rebuild_brief_summary(
            combined, previous_question=previous, followup=False, explicit_document_addition=True
        ))

    def test_explicit_document_addition_is_recognized_and_pinned(self):
        question = "Ты не взял в сводку результат колоноскопии"
        self.assertTrue(assistant._looks_like_explicit_document_addition(question))
        self.assertEqual(assistant._explicitly_requested_document_types(question), ["colonoscopy"])
        self.assertFalse(assistant._looks_like_explicit_document_addition("Что показывает колоноскопия?"))
        self.assertTrue(assistant._looks_like_explicit_document_addition("Ты пропустил результат колоноскопии"))

    def test_summary_selection_is_patient_balanced_diverse_and_includes_requested_old_study(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "Выписной эпикриз 2024.pdf", "kind": "выписной эпикриз", "date": "01.02.2024", "text": "Стационар", "_search_score": 1},
            {"id": 2, "patient": "Олег", "name": "Выписной эпикриз 2026.pdf", "kind": "выписной эпикриз", "date": "01.02.2026", "text": "Стационар", "_search_score": 1},
            {"id": 3, "patient": "Олег", "name": "Протокол колоноскопии.pdf", "kind": "эндоскопическое заключение", "date": "01.02.2023", "text": "Колоноскопия выполнена", "_search_score": 1},
            {"id": 4, "patient": "Олег", "name": "УЗИ сердца.pdf", "kind": "заключение УЗИ", "date": "01.03.2026", "text": "УЗИ сердца, эхокардиография", "_search_score": 1},
            {"id": 5, "patient": "Олег", "name": "ОАК 2026.pdf", "kind": "лабораторный отчёт", "date": "01.04.2026", "text": "Общий анализ крови: гемоглобин", "_search_score": 1},
            {"id": 6, "patient": "Саша", "name": "Выписной эпикриз Саши.pdf", "kind": "выписной эпикриз", "date": "01.02.2025", "text": "Стационар", "_search_score": 1},
            {"id": 7, "patient": "Саша", "name": "МРТ головного мозга.pdf", "kind": "заключение МРТ", "date": "01.05.2026", "text": "МРТ головного мозга", "_search_score": 1},
        ]
        selected = assistant._select_summary_documents(
            rows, ["Олег", "Саша"], limit=6, requested_types=["colonoscopy"]
        )
        ids = [row["id"] for row in selected]
        self.assertEqual(len(selected), 6)
        self.assertIn(3, ids, "an explicitly requested colonoscopy must survive even if it is older")
        self.assertIn(2, ids, "the latest discharge should replace an older duplicate of the same type")
        self.assertNotIn(1, ids)
        self.assertIn("Саша", {row["patient"] for row in selected})
        self.assertIn("Олег", {row["patient"] for row in selected})
        self.assertLessEqual(len(selected), 6)

    def test_explicit_document_is_prioritized_in_non_summary_analysis_too(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "Скан обследования.pdf", "kind": "эндоскопическое заключение", "date": "01.02.2022", "text": "Колоноскопия выполнена"},
        ] + [
            {"id": index, "patient": "Олег", "name": f"Новый документ {index}.pdf", "kind": "документ", "date": f"{index:02d}.10.2026", "text": "Прочий документ", "_search_score": 100}
            for index in range(2, 22)
        ]
        selected = assistant._prioritize_requested_document_rows(rows, ["Олег"], ["colonoscopy"], limit=15)
        self.assertEqual(selected[0]["id"], 1)
        self.assertIn(1, [row["id"] for row in selected])
        self.assertEqual(len(selected), 15)

    def test_unknown_lab_panels_with_generic_filenames_use_extracted_analytes(self):
        first = {"id": 60, "patient": "Олег", "name": "scan.pdf", "kind": "лабораторный отчёт",
                 "analysis": {"lab_results": [{"name": "Амилаза", "value": "45"}]}, "text": ""}
        second = {"id": 61, "patient": "Олег", "name": "scan.pdf", "kind": "лабораторный отчёт",
                  "analysis": {"lab_results": [{"name": "Витамин D", "value": "30"}]}, "text": ""}
        self.assertNotEqual(assistant._summary_document_class(first)[1], assistant._summary_document_class(second)[1])

    def test_document_type_uses_indexed_identity_not_incidental_ocr_references(self):
        ultrasound = {
            "id": 52, "patient": "Олег", "name": "УЗИ сердца.pdf", "kind": "заключение УЗИ",
            "date": "01.06.2026", "text": "Заключение УЗИ сердца. В анамнезе упомянута колоноскопия; рекомендована выписка.",
        }
        doc_class, group_key, _priority = assistant._summary_document_class(ultrasound)
        self.assertEqual(doc_class, "investigation")
        self.assertEqual(group_key, "ultrasound:heart")
        self.assertFalse(assistant._row_matches_requested_document_type(ultrasound, "colonoscopy"))

    def test_summary_selection_fails_closed_on_patient_mismatch(self):
        rows = [
            {"id": 1, "patient": "Саша", "name": "Выписка.pdf", "kind": "выписной эпикриз", "date": "01.02.2026", "text": "Стационар"},
        ]
        selected = assistant._select_summary_documents(rows, ["Олег"], limit=15)
        self.assertEqual(selected, [])

    def test_all_summary_candidates_can_be_retrieved_before_global_cap(self):
        rows = [
            {"id": index, "patient": "Олег", "name": f"Документ {index}.pdf", "kind": "документ", "date": f"{index:02d}.01.2026", "_search_score": 0}
            for index in range(1, 21)
        ]
        with patch("assistant_routes.db.search", return_value=rows):
            selected = assistant._retrieve(12, "Олег", {"search_terms": [], "allow_full_history": True}, result_limit=None)
        self.assertEqual(len(selected), 20)
        self.assertEqual(len(assistant._select_summary_documents(selected, ["Олег"], limit=15)), 15)

    def test_document_context_labels_each_patient(self):
        context = assistant._context([{"id": 44, "patient": "Олег", "name": "ОАК.pdf", "date": "2026-10-01", "kind": "лабораторный отчёт", "text": "Гемоглобин"}])
        self.assertIn("Пациент: Олег", context)
        self.assertIn("ID источника в архиве: 44", context)

    def test_explicit_document_listing_stays_local(self):
        question = "Покажи последние ФЛГ всех членов семьи"
        self.assertTrue(assistant._is_document_listing_request(question))
        self.assertFalse(assistant._needs_ai_analysis(question))

    def test_full_archive_access_requires_explicit_request(self):
        self.assertTrue(assistant._explicit_full_history("Покажи все документы Саши"))
        self.assertTrue(assistant._explicit_full_history("Сделай сводку по всей истории здоровья"))
        self.assertFalse(assistant._explicit_full_history("Дай краткую сводку по УЗИ Саши"))

    def test_search_terms_remove_function_words_and_expand_ultrasound(self):
        terms = assistant._local_search_terms("Что по УЗИ и ультразвуковому исследованию")
        self.assertIn("узи", terms)
        self.assertIn("ультразвуковое", terms)
        self.assertNotIn("по", terms)
        self.assertNotIn("исследованию", terms)

    def test_fallback_plan_does_not_treat_common_words_as_archive_terms(self):
        plan = assistant._fallback_plan("что по для об")
        self.assertEqual(plan["search_terms"], [])
        self.assertFalse(plan["allow_full_history"])

    @patch("assistant_routes.db.search", return_value=[])
    def test_planner_phrase_is_split_into_specific_terms(self, search):
        assistant._retrieve(
            12, "Александр",
            {"search_terms": ["ультразвуковое исследование"], "allow_full_history": False},
        )
        terms = [call.args[2] for call in search.call_args_list]
        self.assertIn("ультразвуковое", terms)
        self.assertNotIn("исследование", terms)
        self.assertNotIn("ультразвуковое исследование", terms)

    def test_patient_alias_inflection_scopes_sasha(self):
        records = [{"name": "Александр", "aliases": ["Александр", "Саша"]}]
        self.assertEqual(assistant._mentioned_people(records, "Дай сводку по УЗИ Саши"), ["Александр"])

    def test_registered_alexander_matches_common_sasha_nickname(self):
        records = [{"name": "Александр", "aliases": ["Александр"]}]
        self.assertEqual(assistant._mentioned_people(records, "Дай сводку по УЗИ Саши"), ["Александр"])

    def test_ambiguous_shared_nickname_is_not_resolved_to_multiple_patients(self):
        records = [
            {"name": "Александр Иванов", "aliases": ["Саша"]},
            {"name": "Александра Петрова", "aliases": ["Саша"]},
        ]
        matched = assistant._mentioned_people(records, "Что известно про Сашу?")
        self.assertEqual(matched, ["Александр Иванов", "Александра Петрова"])
        self.assertTrue(assistant._has_ambiguous_nickname_reference(records, "Что известно про Сашу?", matched))

    def test_explicit_name_disambiguates_shared_nickname(self):
        records = [
            {"name": "Александр Иванов", "aliases": ["Саша"]},
            {"name": "Александра Петрова", "aliases": ["Саша"]},
            {"name": "Олег", "aliases": ["Олег"]},
        ]
        matched = assistant._mentioned_people(records, "Что известно про Сашу и Олега?")
        self.assertEqual(matched, ["Александр Иванов", "Александра Петрова", "Олег"])
        self.assertTrue(assistant._has_ambiguous_nickname_reference(records, "Что известно про Сашу и Олега?", matched))

    def test_full_name_disambiguates_shared_nickname(self):
        records = [
            {"name": "Александр Иванов", "aliases": ["Саша"]},
            {"name": "Александра Петрова", "aliases": ["Саша"]},
        ]
        question = "Расскажи про Александра Иванова"
        matched = assistant._mentioned_people(records, question)
        self.assertEqual(matched, ["Александр Иванов"])
        self.assertFalse(assistant._has_ambiguous_nickname_reference(records, question, matched))

    def test_canonical_name_still_matches_when_aliases_only_contain_nickname(self):
        records = [{"name": "Храмцов Александр Михайлович", "aliases": ["Саша"]}]
        self.assertEqual(
            assistant._mentioned_people(records, "Расскажи, что известно про Александра"),
            ["Храмцов Александр Михайлович"],
        )
        self.assertEqual(
            assistant._mentioned_people(records, "Расскажи про Храмцова Александра Михайловича"),
            ["Храмцов Александр Михайлович"],
        )

    def test_registered_oleg_matches_genitive_form(self):
        records = [{"name": "Олег", "aliases": ["Олег"]}]
        self.assertEqual(assistant._mentioned_people(records, "А что у Олега?"), ["Олег"])

    def test_sashka_forms_match_registered_alexander_and_full_name(self):
        full_name = "Храмцов Александр Михайлович"
        records = [{"name": full_name, "aliases": [full_name]}]
        for question in ("Дай краткий анализ по Сашке", "Расскажи про Сашки", "Что известно о Сашке?"):
            with self.subTest(question=question):
                self.assertEqual(assistant._mentioned_people(records, question), [full_name])

    def test_document_patient_boundary_fails_closed(self):
        self.assertTrue(assistant._row_matches_patient({"patient": "Олег"}, "Олег"))
        self.assertTrue(assistant._row_matches_patient({"patient": " олег "}, "Олег"))
        self.assertFalse(assistant._row_matches_patient({"patient": "Саша"}, "Олег"))
        self.assertFalse(assistant._row_matches_patient({"patient": ""}, "Олег"))
        self.assertFalse(assistant._row_matches_patient({}, "Олег"))

    def test_patient_name_only_followup_inherits_topic_but_full_request_does_not(self):
        self.assertTrue(assistant._looks_like_patient_topic_ellipsis("А что у Олега?", ["Олег"]))
        self.assertTrue(assistant._looks_like_patient_topic_ellipsis("У Олега", ["Олег"]))
        self.assertFalse(assistant._looks_like_patient_topic_ellipsis("А что у Олега по крови?", ["Олег"]))
        self.assertFalse(assistant._looks_like_patient_topic_ellipsis("Расскажи про пользователя Тест", ["Тест"]))

    def test_switching_patient_keeps_prior_question_but_drops_prior_answer(self):
        history = assistant._history_for_current_patient(
            {"question": "Что по крови у Саши?", "answer": "У Саши гемоглобин 110."},
            ["Олег"], ["Саша"],
        )
        self.assertEqual(len(history), 1)
        self.assertIn("Что по крови у Саши?", history[0])
        self.assertNotIn("гемоглобин 110", history[0])

    def test_conversation_history_requires_matching_family_and_patient_scope(self):
        raw = [
            {"family_id": 1, "patient_scope": "Саша", "question": "Вопрос Саши", "answer": "Ответ Саши"},
            {"family_id": 1, "patient_scope": "Олег", "question": "Вопрос Олега", "answer": "Ответ Олега"},
            {"family_id": 2, "patient_scope": "Саша", "question": "Чужая семья", "answer": "Чужой ответ"},
            {"family_id": 1, "patient_scope": None, "question": "Семейный чат", "answer": "Общий ответ"},
        ]
        self.assertEqual(
            assistant._normalize_conversation(raw, 1, "Саша"),
            [{"question": "Вопрос Саши", "answer": "Ответ Саши"}],
        )
        self.assertEqual(
            assistant._normalize_conversation(raw, 1, None),
            [{"question": "Семейный чат", "answer": "Общий ответ"}],
        )

    def test_conversation_history_rejects_malformed_untagged_and_oversized_entries(self):
        raw = [
            {"question": "Без family ID", "answer": "Не принимать"},
            {"family_id": "not-an-id", "patient_scope": None, "question": "Некорректный ID"},
            {"family_id": 1, "patient_scope": None, "question": "   ", "answer": "Пустой вопрос"},
        ] + [
            {"family_id": 1, "patient_scope": None, "question": f"Вопрос {i}", "answer": "A" * 1000}
            for i in range(7)
        ]
        normalized = assistant._normalize_conversation(raw, 1, None)
        self.assertEqual(len(normalized), 5)
        self.assertEqual([turn["question"] for turn in normalized], [f"Вопрос {i}" for i in range(2, 7)])
        self.assertEqual(len(normalized[-1]["answer"]), 900)

    def test_same_patient_followup_keeps_dialogue_answer_as_non_evidence(self):
        history = assistant._history_for_current_patient(
            {"question": "Что по крови у Саши?", "answer": "Гемоглобин 110."},
            ["Саша"], ["Саша"],
        )
        self.assertIn("Гемоглобин 110", history[0])
        self.assertIn("не медицинский источник", history[0])

    def test_standalone_general_question_does_not_inherit_chat_context(self):
        self.assertTrue(assistant._looks_like_standalone_general_question("Что такое метеоризм?"))
        self.assertFalse(assistant._looks_like_standalone_general_question("А что это значит для Саши?"))

    def test_contextual_medical_followups_are_recognized(self):
        for question in (
            "Какие можно ещё дать рекомендации по такому ребёнку?",
            "А какие можно ещё дать рекомендации по Саше? Что ещё можно поделать?",
            "Что ещё можно сделать для этого ребёнка?",
            "Какие ещё варианты можно обсудить?",
        ):
            with self.subTest(question=question):
                self.assertTrue(assistant._looks_like_contextual_medical_followup(question))

    def test_standalone_definition_is_not_mistaken_for_contextual_followup(self):
        self.assertFalse(assistant._looks_like_contextual_medical_followup("Что такое метеоризм?"))
        self.assertFalse(assistant._looks_like_contextual_medical_followup("Сколько будет два плюс два?"))

    def test_patient_measurement_statement_is_a_followup_fragment(self):
        self.assertTrue(assistant._looks_like_patient_fact_fragment("Саше, рост ~125 см, вес ~15 кг"))
        found = assistant._extract_memory_measurements("Саше, рост ~125 см, вес ~15 кг")
        by_key = {item["memory_key"]: item["text"] for item in found}
        self.assertEqual(by_key["height_cm"], "Рост: около 125 см")
        self.assertEqual(by_key["weight_kg"], "Вес: около 15 кг")

    def test_sasha_dative_form_is_recognized(self):
        records = [{"name": "Александр", "aliases": ["Александр"]}]
        self.assertEqual(assistant._mentioned_people(records, "Нужно дать парацетамол Саше"), ["Александр"])

    def test_sasha_dative_form_matches_a_full_legal_name_and_alias(self):
        full_name = "Храмцов Александр Михайлович"
        self.assertEqual(
            assistant._mentioned_people([{"name": full_name, "aliases": [full_name]}], "Нужно дать парацетамол Саше"),
            [full_name],
        )
        self.assertEqual(
            assistant._mentioned_people([{"name": full_name, "aliases": [full_name, "Саша"]}], "Вес Саши около 15 кг"),
            [full_name],
        )

    def test_structured_answer_extracts_missing_document_and_limitations(self):
        raw = (
            '{"answer":"По найденным документам можно сделать предварительную сводку.",'
            '"missing_documents":[{"name":"Заключение эпилептолога","reason":"На него есть ссылка в заключении УЗИ."}],'
            '"limitations":["Нет текста упомянутого заключения."],"data_completeness":"partial"}'
        )
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "По найденным документам можно сделать предварительную сводку.")
        self.assertEqual(parsed["missing_documents"][0]["name"], "Заключение эпилептолога")
        self.assertEqual(parsed["data_completeness"], "partial")

    def test_plain_answer_does_not_leak_structured_transport_fields(self):
        raw = (
            "В архиве есть несколько документов; выводы ограничены их содержимым.\n\n"
            'missing_documents: [{"name": "заключение", "reason": "нет полного текста"}]\n'
            'limitations: ["нельзя подтвердить диагноз"]\n'
            'data_completeness: "partial"\n'
            'memory_updates: []'
        )
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "В архиве есть несколько документов; выводы ограничены их содержимым.")
        for field in ("missing_documents", "limitations", "data_completeness", "memory_updates"):
            self.assertNotIn(field, parsed["answer"])

    @patch("assistant_routes.db.search", return_value=[])
    def test_empty_retrieval_does_not_silently_fetch_entire_archive(self, search):
        result = assistant._retrieve(
            12, "Александр",
            {"search_terms": ["по", "для", "заключение"], "allow_full_history": False},
        )
        self.assertEqual(result, [])
        search.assert_not_called()

    @patch("assistant_routes.db.search", return_value=[])
    def test_explicit_full_history_can_fetch_archive(self, search):
        result = assistant._retrieve(
            12, "Александр",
            {"search_terms": [], "allow_full_history": True},
        )
        self.assertEqual(result, [])
        search.assert_called_once_with(12, "Александр", "", limit=1000)

    @patch("assistant_routes.db.search")
    def test_referenced_document_is_checked_locally_before_marking_missing(self, search):
        candidate = {
            "id": 41, "patient": "Александр", "name": "epilepsy_report_2024.pdf",
            "kind": "заключение эпилептолога", "date": "12-02-2024",
            "_search_score": 101, "text": "Заключение врача",
        }
        search.return_value = [candidate]
        extra, matched = assistant._search_referenced_documents(
            12, ["Александр"],
            [{"name": "Заключение эпилептолога", "reason": "На документ есть ссылка."}],
            set(),
        )
        self.assertEqual([row["id"] for row in extra], [41])
        self.assertEqual(matched["заключение эпилептолога"], {41})
        search.assert_called_with(12, "Александр", "эпилептолога", limit=30)

    def test_comparison_intent_and_study_types_are_detected_without_addition_language(self):
        self.assertTrue(assistant._is_comparison_request("Сравни показатели крови Саши и Олега"))
        self.assertTrue(assistant._is_comparison_request("Какая разница между последними ОАК?"))
        self.assertEqual(assistant._comparison_requested_document_types("Сравни последние ОАК Саши и Олега"), ["cbc"])
        self.assertEqual(assistant._comparison_requested_document_types("Сравни последние УЗИ Саши и Олега"), ["ultrasound"])
        self.assertTrue(assistant._comparison_asks_blood_labs("Сравни показатели крови Саши и Олега", []))
        self.assertFalse(assistant._comparison_asks_blood_labs("Сравни последние ОАК Саши и Олега", ["cbc"]))
        self.assertFalse(assistant._comparison_requests_previous("Сравни последние анализы Саши и Олега"))
        self.assertTrue(assistant._comparison_requests_previous("Сравни последние анализы с предыдущими"))
        self.assertTrue(assistant._comparison_requests_all_results("Сравни все анализы крови за полгода"))
        self.assertFalse(assistant._comparison_requests_all_results("Сравни последние анализы крови"))
        self.assertEqual(assistant._comparison_requested_anatomy("Сравни последние УЗИ сердца"), "heart")

    def test_latest_blood_comparison_uses_each_patient_latest_date_and_distinct_panels(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "ОАК.pdf", "kind": "лабораторный отчёт", "date": "01.09.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "130"}]}, "text": "старый анализ"},
            {"id": 2, "patient": "Олег", "name": "ОАК.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "140"}]}, "text": "последний ОАК"},
            {"id": 3, "patient": "Олег", "name": "ОАК копия.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "140"}]}, "text": "дубликат последнего ОАК"},
            {"id": 4, "patient": "Олег", "name": "Биохимия.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "analysis": {"lab_results": [{"name": "АЛТ", "value": "20"}]}, "text": "последняя биохимия"},
            {"id": 5, "patient": "Олег", "name": "УЗИ.pdf", "kind": "УЗИ", "date": "11.10.2026", "text": "упомянут анализ крови"},
            {"id": 6, "patient": "Саша", "name": "ОАК Саши.pdf", "kind": "лабораторный отчёт", "date": "09.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "115"}]}, "text": "последний ОАК"},
            {"id": 7, "patient": "Саша", "name": "Биохимия старая.pdf", "kind": "лабораторный отчёт", "date": "20.08.2026", "analysis": {"lab_results": [{"name": "АЛТ", "value": "23"}]}, "text": "старый результат"},
        ]
        selected = assistant._select_latest_comparison_documents(rows, ["Олег", "Саша"], broad_blood=True)
        selected_ids = {row["id"] for row in selected}
        self.assertTrue(selected_ids & {2, 3}, "one latest CBC source must be selected")
        self.assertIn(4, selected_ids)
        self.assertIn(6, selected_ids)
        self.assertNotIn(1, selected_ids)
        self.assertFalse({2, 3}.issubset(selected_ids), "a duplicate same-day CBC must not be sent twice")
        self.assertNotIn(5, selected_ids, "an ultrasound that only mentions blood tests is not a blood-lab source")
        self.assertNotIn(7, selected_ids, "older lab dates are excluded from a latest-only comparison")
        self.assertEqual({row["patient"] for row in selected}, {"Олег", "Саша"})

    def test_comparison_with_previous_results_keeps_two_distinct_dates_per_patient(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "ОАК newest.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "140"}]}},
            {"id": 2, "patient": "Олег", "name": "ОАК prior.pdf", "kind": "лабораторный отчёт", "date": "01.09.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "130"}]}},
            {"id": 3, "patient": "Олег", "name": "ОАК oldest.pdf", "kind": "лабораторный отчёт", "date": "01.08.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "120"}]}},
            {"id": 4, "patient": "Саша", "name": "ОАК newest.pdf", "kind": "лабораторный отчёт", "date": "09.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "115"}]}},
            {"id": 5, "patient": "Саша", "name": "ОАК prior.pdf", "kind": "лабораторный отчёт", "date": "20.08.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "110"}]}},
        ]
        selected = assistant._select_latest_comparison_documents(rows, ["Олег", "Саша"], broad_blood=True, include_previous=True)
        ids = {row["id"] for row in selected}
        self.assertEqual(ids, {1, 2, 4, 5})
        self.assertNotIn(3, ids, "trend mode should include latest and previous, not every historical result")
        self.assertEqual(sum(1 for row in selected if row.get("_comparison_position") == "latest"), 2)
        self.assertEqual(sum(1 for row in selected if row.get("_comparison_position") == "previous"), 2)

    def test_comparison_of_explicit_study_type_picks_latest_per_patient(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "ОАК-old.pdf", "kind": "лабораторный отчёт", "date": "01.09.2026", "text": "общий анализ крови"},
            {"id": 2, "patient": "Олег", "name": "ОАК-new.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "text": "общий анализ крови"},
            {"id": 3, "patient": "Саша", "name": "ОАК.pdf", "kind": "лабораторный отчёт", "date": "09.10.2026", "text": "общий анализ крови"},
        ]
        selected = assistant._select_latest_comparison_documents(rows, ["Олег", "Саша"], requested_types=["cbc"])
        self.assertEqual({row["id"] for row in selected}, {2, 3})

    def test_explicit_cbc_comparison_can_use_analytes_when_filename_is_generic(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "scan.pdf", "kind": "лабораторный отчёт", "date": "10.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "140"}]}},
            {"id": 2, "patient": "Саша", "name": "scan-2.pdf", "kind": "лабораторный отчёт", "date": "09.10.2026", "analysis": {"lab_results": [{"name": "Гемоглобин", "value": "115"}]}},
        ]
        selected = assistant._select_latest_comparison_documents(rows, ["Олег", "Саша"], requested_types=["cbc"])
        self.assertEqual({row["id"] for row in selected}, {1, 2})

    def test_imaging_comparison_filters_to_requested_anatomy(self):
        rows = [
            {"id": 1, "patient": "Олег", "name": "УЗИ сердца.pdf", "kind": "заключение УЗИ", "date": "10.10.2026", "text": "Эхокардиография"},
            {"id": 2, "patient": "Олег", "name": "УЗИ брюшной полости.pdf", "kind": "заключение УЗИ", "date": "11.10.2026", "text": "Печень и желчный пузырь"},
            {"id": 3, "patient": "Саша", "name": "УЗИ сердца.pdf", "kind": "заключение УЗИ", "date": "09.10.2026", "text": "Эхокардиография"},
            {"id": 4, "patient": "Саша", "name": "УЗИ головного мозга.pdf", "kind": "заключение УЗИ", "date": "12.10.2026", "text": "Нейросонография"},
        ]
        selected = assistant._select_latest_comparison_documents(
            rows, ["Олег", "Саша"], requested_types=["ultrasound"], requested_anatomy="heart"
        )
        self.assertEqual({row["id"] for row in selected}, {1, 3})



    def test_four_family_members_recognize_common_name_cases_and_nicknames(self):
        cases = [
            ("Олег", ["Олег", "Олега", "Олегу", "Олеге", "Олегом", "Олежка", "Олежке", "Олежкой"]),
            ("Юлия", ["Юля", "Юли", "Юле", "Юлю", "Юлей", "Юлия", "Юлии", "Юлию", "Юлечка", "Юлечке"]),
            ("Александр", ["Саша", "Саши", "Саше", "Сашу", "Сашкой", "Сашка", "Сашке", "Саня", "Сане", "Сашенька"]),
            ("Мария", ["Маша", "Маши", "Маше", "Машу", "Машей", "Машка", "Машке", "Машенька"]),
        ]
        for registered_name, forms in cases:
            records = [{"name": registered_name, "aliases": [registered_name]}]
            for form in forms:
                with self.subTest(registered_name=registered_name, form=form):
                    self.assertEqual(assistant._mentioned_people(records, f"Расскажи про {form}"), [registered_name])

    def test_family_nicknames_do_not_cross_match_other_registered_patients(self):
        records = [
            {"name": "Олег", "aliases": ["Олег"]},
            {"name": "Юлия", "aliases": ["Юлия"]},
            {"name": "Александр", "aliases": ["Александр"]},
            {"name": "Мария", "aliases": ["Мария"]},
        ]
        for form, expected in [
            ("Олежка", ["Олег"]),
            ("Юлечке", ["Юлия"]),
            ("Сашкой", ["Александр"]),
            ("Машеньке", ["Мария"]),
        ]:
            with self.subTest(form=form):
                self.assertEqual(assistant._mentioned_people(records, f"Расскажи про {form}"), expected)



    def test_structured_answer_extracts_json_wrapped_in_commentary(self):
        raw = 'Результат анализа:\n```json\n{"answer":"Саша: обследования за 2025 год.","missing_documents":[],"limitations":[],"data_completeness":"partial","memory_updates":[{"text":"не показывать это"}]}\n```\nГотово.'
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "Саша: обследования за 2025 год.")
        self.assertNotIn("memory_updates", parsed["answer"])

if __name__ == "__main__":
    unittest.main()
