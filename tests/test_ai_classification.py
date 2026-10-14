import unittest
from unittest.mock import patch
from AIAnalise import analyze_document, classify_with_ai

class AIClassificationTests(unittest.TestCase):
    def test_allowlisted_ai_type_can_refine_rule_based_result(self):
        base = analyze_document("Медицинский документ без ясного заголовка")
        with patch("ai_provider.chat_completion", return_value='{"primary_type":"лабораторный отчёт","document_types":["лабораторный отчёт"],"confidence":"high"}'):
            result = classify_with_ai("Гемоглобин 120 г/л", base)
        self.assertEqual(result["primary_type"], "лабораторный отчёт")
        self.assertEqual(result["classification_source"], "rules+ai")
        self.assertTrue(result["review_required"])

    def test_invalid_ai_type_does_not_override_local_result(self):
        base = analyze_document("Гемоглобин 120 г/л")
        with patch("ai_provider.chat_completion", return_value='{"primary_type":"политическая статья","document_types":[],"confidence":"high"}'):
            result = classify_with_ai("Гемоглобин 120 г/л", base)
        self.assertEqual(result["primary_type"], base["primary_type"])
        self.assertNotIn("classification_source", result)

    def test_low_confidence_does_not_override_local_result(self):
        base = analyze_document("Гемоглобин 120 г/л")
        with patch("ai_provider.chat_completion", return_value='{"primary_type":"заключение УЗИ","document_types":["заключение УЗИ"],"confidence":"low"}'):
            result = classify_with_ai("Гемоглобин 120 г/л", base)
        self.assertEqual(result["primary_type"], base["primary_type"])

if __name__ == "__main__":
    unittest.main()