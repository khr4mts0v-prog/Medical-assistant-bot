import unittest
from unittest.mock import patch

import assistant_routes as assistant


class ClinicalContextQualityTests(unittest.TestCase):
    def test_consultation_context_includes_conclusion_and_recommendations_at_end(self):
        ocr = (
            "Начальная часть анамнеза. " * 130
            + "\nЗаключение консультации: Цитофлавин 1 таблетка два раза в день. "
            + "Кавинтон 5 мг утром и 10 мг вечером, 3 месяца.\n"
            + "Режим и рекомендации: вакцинация без живых вакцин; постоянные занятия ЛФК; массаж."
        )
        context = assistant._context([{
            "id": 12,
            "patient": "Александр",
            "name": "консультация_невролога.pdf",
            "kind": "консультация специалиста",
            "date": "14-09-2026",
            "text": ocr,
            "analysis": {"primary_type": "консультация специалиста"},
        }])
        self.assertIn("ПОЛНЫЙ OCR-ТЕКСТ КЛИНИЧЕСКОГО ДОКУМЕНТА", context)
        self.assertIn("Заключение консультации", context)
        self.assertIn("Цитофлавин", context)
        self.assertIn("Кавинтон 5 мг утром и 10 мг вечером, 3 месяца", context)
        self.assertIn("вакцинация без живых вакцин", context)

    def test_nonclinical_document_keeps_bounded_ocr_excerpt(self):
        ocr = "A" * 2500 + "UNIQUE_END_MARKER"
        context = assistant._context([{
            "id": 20,
            "patient": "Олег",
            "name": "scan.pdf",
            "kind": "документ",
            "date": "01-10-2026",
            "text": ocr,
            "analysis": {},
        }])
        self.assertIn("Фрагмент OCR", context)
        self.assertNotIn("UNIQUE_END_MARKER", context)

    def test_additional_recommendation_prompt_separates_archive_facts_from_options(self):
        with patch(
            "assistant_routes.chat_completion",
            return_value='{"answer":"Обсудите варианты с лечащим врачом.","missing_documents":[],"limitations":[],"data_completeness":"general"}',
        ) as completion:
            result = assistant._structured_archive_answer(
                "Что ещё можно сделать для Саши?", ["Саша"], [],
                history=["Какие рекомендации по консультации невролога?"],
            )
        self.assertIn("Обсудите варианты", result["answer"])
        system_prompt = completion.call_args.args[0][0]["content"]
        self.assertIn("не ограничивайся повторением архива", system_prompt)
        self.assertIn("не приписывай их врачу", system_prompt)
        self.assertIn("Не выводи противопоказания к вакцинации", system_prompt)

    def test_parser_removes_double_encoded_internal_schema_from_answer(self):
        raw = r'{"answer":"Назначено лечение.\\n\\nmissing_documents: []\\nlimitations: []\\ndata_completeness: partial\\nmemory_updates: []"}'
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "Назначено лечение.")
        self.assertNotIn("missing_documents:", parsed["answer"])
        self.assertNotIn("data_completeness:", parsed["answer"])


if __name__ == "__main__":
    unittest.main()

