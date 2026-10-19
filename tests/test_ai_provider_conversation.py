import unittest
from unittest.mock import patch

import ai_provider


class AIProviderConversationTests(unittest.TestCase):
    def test_nested_json_in_history_is_unwrapped(self):
        self.assertEqual(
            ai_provider._history_answer_text('{"answer":"{\\"answer\\":\\"Useful answer.\\"}"}'),
            "Useful answer.",
        )

    def test_structured_payload_without_answer_is_not_reused_as_history(self):
        self.assertEqual(ai_provider._history_answer_text('{"limitations":[],"data_completeness":"partial"}'), "")

    def test_history_answer_remains_bounded(self):
        self.assertEqual(len(ai_provider._history_answer_text("А" * 1500)), 1100)

    @patch("ai_provider.chat_completion", return_value="А" * 1500)
    def test_current_general_answer_is_not_truncated_to_history_limit(self, completion):
        answer = ai_provider.answer_archive_question(
            "Объясни подробнее", "не идентифицирован", history=[]
        )
        self.assertEqual(len(answer), 1500)
        self.assertEqual(answer, "А" * 1500)

    @patch("ai_provider.chat_completion", return_value={
        "content": "Частичный ответ",
        "metadata": {"finish_reason": "length", "completion_tokens": 750, "requested_max_tokens": 750},
    })
    def test_length_finish_reason_adds_visible_truncation_warning(self, completion):
        answer = ai_provider.answer_archive_question("Вопрос", "не идентифицирован")
        self.assertIn("Частичный ответ", answer)
        self.assertIn("Ответ мог быть обрезан лимитом генерации", answer)
        self.assertTrue(completion.call_args.kwargs["return_metadata"])

    @patch("ai_provider.requests.post")
    @patch("ai_provider.provider_config", return_value=("polza", "test-token", "https://provider.invalid", "test-model", "POLZA_API_KEY"))
    def test_chat_completion_returns_finish_reason_and_usage_when_requested(self, provider_config, post):
        response = post.return_value
        response.json.return_value = {
            "choices": [{"message": {"content": "Ответ"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 750, "total_tokens": 873},
        }
        result = ai_provider.chat_completion([], max_tokens=750, return_metadata=True)
        self.assertEqual(result["content"], "Ответ")
        self.assertEqual(result["metadata"]["finish_reason"], "length")
        self.assertEqual(result["metadata"]["prompt_tokens"], 123)
        self.assertEqual(result["metadata"]["completion_tokens"], 750)
        self.assertEqual(result["metadata"]["total_tokens"], 873)
        self.assertEqual(result["metadata"]["requested_max_tokens"], 750)

    @patch("ai_provider.ai_trace_log.emit")
    @patch("ai_provider.ai_trace_log.emit_full")
    @patch("ai_provider.chat_completion", return_value="Короткий ответ без лишнего.")
    def test_general_answer_gets_role_based_history_and_logs_model_io(self, completion, emit_full, emit):
        history = [{"question":"У меня перхоть", "answer":"Используй лечебный шампунь."}]
        answer = ai_provider.answer_archive_question(
            "После обычного шампуня сильно чешется голова", "не идентифицирован",
            history=history, trace_id="trace-test",
        )
        self.assertEqual(answer, "Короткий ответ без лишнего.")
        messages = completion.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertIn("После обычного шампуня", messages[-1]["content"])
        self.assertIn("а не медицинские доказательства", messages[0]["content"])
        self.assertTrue(any(call.args[1] == "general_medical.model_request" for call in emit_full.call_args_list))
        self.assertTrue(any(call.args[1] == "general_medical.model_raw_response" for call in emit_full.call_args_list))
        self.assertTrue(any(call.args[1] == "general_medical.response_visible" for call in emit_full.call_args_list))


if __name__ == "__main__":
    unittest.main()
