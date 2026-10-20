import unittest
from unittest.mock import patch

import assistant_routes
import ai_provider


class MedicalIntentTests(unittest.TestCase):
    def test_common_medical_questions_are_not_rejected_as_off_topic(self):
        for question in (
            "Как дозировать парацетамол?",
            "Что такое метеоризм?",
            "Что делать при вздутии живота?",
            "Можно ли принимать ибупрофен?",
        ):
            with self.subTest(question=question):
                self.assertTrue(assistant_routes._is_archive_related(question))

    def test_clearly_unrelated_questions_are_rejected(self):
        for question in (
            "Напиши программу на Python",
            "Какая сегодня погода?",
            "Расскажи анекдот",
        ):
            with self.subTest(question=question):
                self.assertFalse(assistant_routes._is_archive_related(question))

    def test_ai_classifier_returns_structured_categories(self):
        cases = (
            ('{"category":"medical_general"}', "medical_general"),
            ('{"category":"medical_patient"}', "medical_patient"),
            ('{"category":"non_medical"}', "non_medical"),
            ('{"category":"ambiguous"}', "ambiguous"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                with patch.object(ai_provider, "chat_completion", return_value=raw):
                    self.assertEqual(ai_provider.classify_medical_intent("тестовый вопрос"), expected)

    def test_ai_classifier_falls_back_safely_on_invalid_output(self):
        with patch.object(ai_provider, "chat_completion", return_value="not json"):
            self.assertEqual(ai_provider.classify_medical_intent("тестовый вопрос"), "unknown")
        with patch.object(ai_provider, "chat_completion", side_effect=RuntimeError("offline")):
            self.assertEqual(ai_provider.classify_medical_intent("тестовый вопрос"), "unknown")

    def test_medical_answer_without_archive_context_calls_provider(self):
        with patch.object(ai_provider, "chat_completion", return_value="Общий медицинский ответ") as call:
            answer = ai_provider.answer_archive_question(
                "Что такое метеоризм?", "Тестовый пациент", context=""
            )
        self.assertEqual(answer, "Общий медицинский ответ")
        self.assertIn("не выдавай его за вывод", call.call_args.args[0][0]["content"])

    def test_medical_answer_with_archive_context_calls_provider(self):
        with patch.object(ai_provider, "chat_completion", return_value="Ответ по источникам") as call:
            answer = ai_provider.answer_archive_question(
                "Что сказано в заключении?", "Тестовый пациент", context="Источник: УЗИ; дата: 2026-10-01"
            )
        self.assertEqual(answer, "Ответ по источникам")
        self.assertIn("Источник: УЗИ", call.call_args.args[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
