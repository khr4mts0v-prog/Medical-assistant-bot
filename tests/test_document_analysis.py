import unittest

from AIAnalise import analyze_document, classify_document, extract_keywords


class DocumentAnalysisTests(unittest.TestCase):
    def test_mixed_document_gets_multiple_content_types(self):
        text = """--- Страница 1 ---
Выписной эпикриз из стационара
Основной диагноз: железодефицитная анемия.
Назначено лечение. Принимать препарат по схеме врача.
--- Страница 2 ---
Общий анализ крови
Гемоглобин 115 г/л
Ферритин 16 мкг/л
--- Страница 3 ---
УЗИ органов брюшной полости
Заключение врача: без острых изменений.
"""
        result = analyze_document(text)
        self.assertEqual(result["primary_type"], "выписка")
        self.assertIn("лабораторные анализы", result["types"])
        self.assertIn("УЗИ", result["types"])
        self.assertIn("назначения и лечение", result["types"])
        page_map = {entry["page"]: entry["types"] for entry in result["page_types"]}
        self.assertIn("лабораторные анализы", page_map[2])
        self.assertIn("УЗИ", page_map[3])
        self.assertTrue(any(x["name"] == "гемоглобин" and x["value"] == "115" and x["unit"] == "г/л" and x["page"] == 2 for x in result["lab_results"]))
        self.assertTrue(any(x["name"] == "ферритин" and x["value"] == "16" and x["page"] == 2 for x in result["lab_results"]))
        self.assertTrue(result["diagnoses"])
        self.assertTrue(result["medications"])

    def test_unknown_document_stays_unknown(self):
        result = analyze_document("Квитанция об оплате услуги на сумму 500 рублей")
        self.assertEqual(result["primary_type"], "документ")
        self.assertEqual(result["types"], [])
        self.assertEqual(result["confidence"], "low")

    def test_backward_compatible_classifier_and_keywords(self):
        self.assertEqual(classify_document("УЗИ брюшной полости"), "УЗИ")
        self.assertIn("ферритин", extract_keywords("Ферритин 16 мкг/л"))


if __name__ == "__main__":
    unittest.main()
