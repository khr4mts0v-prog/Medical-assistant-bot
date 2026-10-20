import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")

import ai_provider


class ProviderHttpErrorTests(unittest.TestCase):
    def test_http_error_is_actionable_and_logs_bounded_redacted_details(self):
        response = Mock()
        response.status_code = 429
        response.text = '{"error":"rate limit","token":"secret-value"}'
        response.raise_for_status.side_effect = ai_provider.requests.HTTPError("429 Client Error")

        with (
            patch.dict(os.environ, {
                "AI_PROVIDER": "polza",
                "POLZA_API_KEY": "test-api-key",
                "POLZA_MODEL": "test/model",
                "POLZA_CHAT_COMPLETIONS_URL": "https://provider.example/chat",
            }),
            patch.object(ai_provider.requests, "post", return_value=response),
            patch.object(ai_provider.ai_trace_log, "emit") as emit,
        ):
            with self.assertRaisesRegex(ai_provider.requests.HTTPError, r"HTTP 429 \\(polza/test/model\\)"):
                ai_provider.chat_completion([{"role": "user", "content": "hello"}])

        emit.assert_called_once()
        fields = emit.call_args.kwargs
        self.assertEqual(fields["provider"], "polza")
        self.assertEqual(fields["model"], "test/model")
        self.assertEqual(fields["http_status"], 429)
        self.assertIn("[REDACTED]", fields["response_excerpt"])
        self.assertNotIn("secret-value", fields["response_excerpt"])
        self.assertNotIn("test-api-key", fields["response_excerpt"])
        self.assertLessEqual(len(fields["response_excerpt"]), 800)

    def test_successful_response_keeps_existing_behavior(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "Ответ готов"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }
        with (
            patch.dict(os.environ, {"AI_PROVIDER": "polza", "POLZA_API_KEY": "test-api-key"}),
            patch.object(ai_provider.requests, "post", return_value=response),
        ):
            self.assertEqual(
                ai_provider.chat_completion([{"role": "user", "content": "hello"}]),
                "Ответ готов",
            )


if __name__ == "__main__":
    unittest.main()
