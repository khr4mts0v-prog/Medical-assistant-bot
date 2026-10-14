import unittest
from assistant_routes import _is_archive_related, _off_topic_response

class ArchiveIntentFilterTests(unittest.TestCase):
    def test_medical_archive_queries_are_allowed(self):
        for query in ("Покажи последние ФЛГ всех членов семьи", "Сравни гемоглобин за полгода", "Найди выписной эпикриз", "Что означает ферритин в анализе крови?"):
            with self.subTest(query=query):
                self.assertTrue(_is_archive_related(query))

    def test_unrelated_queries_are_rejected(self):
        for query in ("Какая погода завтра?", "What is the weather tomorrow?", "Объясни политику Центрального банка", "Tell me about politics", "Напиши скрипт на Python", "Напиши код для анализа крови", "Расскажи анекдот", "Explain a Word document", "Покажи акции компании и анализ крови", "Где поесть пиццу?"):
            with self.subTest(query=query):
                self.assertFalse(_is_archive_related(query))
        self.assertIn("только на вопросы", _off_topic_response())

    def test_empty_and_oversized_queries_are_rejected(self):
        self.assertFalse(_is_archive_related(""))
        self.assertFalse(_is_archive_related("x" * 1201))

if __name__ == "__main__":
    unittest.main()