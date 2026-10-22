"""Regression tests for user-facing model response sanitization."""
import unittest

import ai_provider


class ProviderResponseSanitizationTests(unittest.TestCase):
    def test_strips_structured_metadata_after_plain_answer(self):
        raw = "Гемоглобин немного снижен.\\nmissing_documents: []\\nlimitations: []"
        self.assertEqual(
            ai_provider._strip_embedded_structured_fields(raw),
            "Гемоглобин немного снижен.",
        )

    def test_strips_metadata_after_real_newline(self):
        raw = "Проверьте результат с врачом.\nMemory_updates: []"
        self.assertEqual(
            ai_provider._strip_embedded_structured_fields(raw),
            "Проверьте результат с врачом.",
        )

    def test_preserves_ordinary_prose_mentioning_metadata(self):
        raw = "В документе описаны ограничения подвижности."
        self.assertEqual(ai_provider._strip_embedded_structured_fields(raw), raw)

    def test_does_not_remove_json_field_names_inside_serialized_payload(self):
        raw = '{"answer":"Текст ответа","missing_documents":[]}'
        self.assertEqual(ai_provider._strip_embedded_structured_fields(raw), raw)


if __name__ == "__main__":
    unittest.main()
