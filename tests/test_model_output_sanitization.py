import json
import unittest

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


if __name__ == "__main__":
    unittest.main()