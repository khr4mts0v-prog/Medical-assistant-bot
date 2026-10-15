import unittest
from unittest.mock import patch

import assistant_routes as assistant


class AssistantChatGapTests(unittest.TestCase):
    def test_summary_request_routes_to_analysis(self):
        self.assertTrue(assistant._needs_ai_analysis("Дай краткую сводку по УЗИ Саши"))

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


if __name__ == "__main__":
    unittest.main()
