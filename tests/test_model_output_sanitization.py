import json
import unittest
from unittest.mock import patch

import assistant_routes as assistant
from ai_provider import sanitize_model_text


class ModelOutputSanitizationTests(unittest.TestCase):
    def test_removes_qwen_chat_template_tokens_and_channel_headers(self):
        raw = "<|im_start|>assistant<|channel|>final\nГотово. <|im_end|><|fim_suffix|>"
        self.assertEqual(sanitize_model_text(raw), "Готово.")

    def test_removes_reasoning_blocks_and_does_not_leak_unclosed_think(self):
        self.assertEqual(sanitize_model_text("<think>hidden reasoning</think>Ответ"), "Ответ")
        self.assertEqual(sanitize_model_text("Ответ\n<think>hidden reasoning"), "Ответ")

    def test_structured_answer_cleans_control_tokens_inside_answer_and_limits(self):
        payload = {
            "answer": "<|im_start|>assistant\nОтвет без операторов. <|im_end|>",
            "limitations": ["analysis\nНет свежего документа <|im_end|>"],
            "missing_documents": [],
            "data_completeness": "partial",
        }
        raw = "<|im_start|>assistant<|channel|>final\n" + json.dumps(payload, ensure_ascii=False) + "<|fim_suffix|>"
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "Ответ без операторов.")
        self.assertEqual(parsed["limitations"], ["Нет свежего документа"])
        self.assertNotIn("<|", str(parsed))
        self.assertNotIn("assistant", parsed["answer"])

    def test_plain_text_fallback_is_sanitized(self):
        raw = "<|im_start|>assistant<|channel|>final\nОбычный ответ. <|im_end|>"
        self.assertEqual(assistant._parse_structured_answer(raw)["answer"], "Обычный ответ.")

    def test_structured_answer_preserves_content_over_8000_characters(self):
        long_answer = "А" * 9500
        raw = json.dumps({
            "answer": long_answer, "missing_documents": [], "limitations": [],
            "data_completeness": "partial", "memory_updates": [],
        }, ensure_ascii=False)
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(len(parsed["answer"]), 9500)
        self.assertEqual(parsed["answer"], long_answer)

    @patch("assistant_routes.chat_completion", return_value={
        "content": json.dumps({"answer": "Часть ответа", "missing_documents": [],
                               "limitations": [], "data_completeness": "partial"}),
        "metadata": {"finish_reason": "length", "completion_tokens": 1200},
    })
    def test_structured_route_warns_when_provider_reports_token_limit(self, completion):
        result = assistant._structured_archive_answer("Вопрос", ["Олег"], [])
        self.assertIn("Часть ответа", result["answer"])
        self.assertIn("Ответ мог быть обрезан лимитом генерации", result["answer"])
        self.assertEqual(result["generation_status"], "partial")
        self.assertTrue(any("достиг лимита генерации" in item for item in result["limitations"]))
        self.assertTrue(completion.call_args.kwargs["return_metadata"])
        self.assertEqual(completion.call_args.kwargs["max_tokens"], 2400)

    @patch("assistant_routes.chat_completion", return_value={
        "content": '{"answer":"Неполный ответ", "missing_documents":[',
        "metadata": {"finish_reason": "length", "completion_tokens": 2400},
    })
    def test_truncated_structured_json_is_never_reported_as_complete(self, completion):
        result = assistant._structured_archive_answer("Сделай сводку", ["Тестовый пациент"], [])
        self.assertEqual(result["generation_status"], "partial")
        self.assertIn("Неполный ответ", result["answer"])
        self.assertIn("Ответ мог быть обрезан лимитом генерации", result["answer"])
        self.assertNotIn("Не удалось корректно обработать", result["answer"])
        self.assertEqual(result["memory_updates"], [])
        self.assertEqual(result["missing_documents"], [])
        self.assertNotEqual(result["data_completeness"], "sufficient")
        completion.assert_called_once()


    @patch("assistant_routes.chat_completion", return_value={
        "content": '{"answer":"Полезная часть ответа", "missing_documents":[',
        "metadata": {"finish_reason": "length", "completion_tokens": 2400},
    })
    def test_truncated_outer_json_preserves_complete_answer_string(self, completion):
        result = assistant._structured_archive_answer("Сделай сводку", ["Тестовый пациент"], [])
        self.assertIn("Полезная часть ответа", result["answer"])
        self.assertEqual(result["generation_status"], "partial")
        self.assertEqual(result["missing_documents"], [])
        self.assertEqual(result["memory_updates"], [])
        completion.assert_called_once()

    @patch("assistant_routes.chat_completion", return_value={
        "content": '{"answer":"строка оборвана',
        "metadata": {"finish_reason": "length", "completion_tokens": 2400},
    })
    def test_truncated_answer_string_is_not_guessed_or_exposed_as_json(self, completion):
        result = assistant._structured_archive_answer("Сделай сводку", ["Тестовый пациент"], [])
        self.assertIn("Не удалось корректно обработать", result["answer"])
        self.assertNotIn('{"answer"', result["answer"])
        self.assertEqual(result["generation_status"], "partial")
        completion.assert_called_once()

    def test_explicit_memory_command_accepts_bare_height_and_approximate_weight(self):
        self.assertTrue(assistant._looks_like_explicit_memory_command("Запиши в память рост 170, вес ~97кг"))
        values = assistant._extract_memory_measurements("Запиши в память рост 170, вес ~97кг")
        self.assertEqual(values, [
            {"memory_key": "height_cm", "text": "Рост: 170 см", "category": "note"},
            {"memory_key": "weight_kg", "text": "Вес: около 97 кг", "category": "note"},
        ])

    def test_conversational_measurements_are_extracted_without_save_command(self):
        self.assertEqual(assistant._extract_memory_measurements("Мой рост 170 см, вешу примерно 97 кг"), [
            {"memory_key": "height_cm", "text": "Рост: 170 см", "category": "note"},
            {"memory_key": "weight_kg", "text": "Вес: около 97 кг", "category": "note"},
        ])
        self.assertEqual(assistant._extract_memory_measurements("Врач сказал, что я вешу 97 кг"), [
            {"memory_key": "weight_kg", "text": "Вес: 97 кг", "category": "note"},
        ])
        self.assertEqual(assistant._extract_memory_measurements("У Саши вес 18 кг"), [
            {"memory_key": "weight_kg", "text": "Вес: 18 кг", "category": "note"},
        ])

    def test_hypothetical_or_question_measurements_are_not_extracted(self):
        self.assertEqual(assistant._extract_memory_measurements("Если вес 97 кг, какая нужна дозировка?"), [])
        self.assertEqual(assistant._extract_memory_measurements("Допустим, рост 170 см"), [])

    def test_measurements_without_units_need_explicit_save_command(self):
        self.assertEqual(assistant._extract_memory_measurements("У него рост 170, вес 97"), [])

    def test_explicit_memory_command_rejects_implausible_measurements(self):
        self.assertEqual(assistant._extract_memory_measurements("Запиши в память рост 900 см, вес 0 кг"), [])

    def test_unwraps_double_serialized_answer(self):
        inner = {"answer": "Короткий ответ.", "missing_documents": [], "limitations": [], "data_completeness": "general"}
        raw = json.dumps({"answer": json.dumps(inner, ensure_ascii=False)}, ensure_ascii=False)
        parsed = assistant._parse_structured_answer(raw)
        self.assertEqual(parsed["answer"], "Короткий ответ.")
        self.assertEqual(parsed["data_completeness"], "general")

    def test_malformed_json_is_never_returned_as_visible_answer(self):
        raw = '{"answer":"Это незакрытый JSON", "limitations": ['
        answer = assistant._parse_structured_answer(raw)["answer"]
        self.assertNotIn('{"answer"', answer)
        self.assertIn("Не удалось корректно обработать", answer)


if __name__ == "__main__":
    unittest.main()
