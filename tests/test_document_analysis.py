import unittest
from AIAnalise import analyze_document, classify_document, extract_keywords


class DocumentClassificationTests(unittest.TestCase):
    def test_clear_document_types(self):
        cases = [
            ("EPICRISIS", "Выписной эпикриз из стационара\nОсновной диагноз: бронхит\nРекомендации при выписке", "выписной эпикриз"),
            ("CBC", "РЕЗУЛЬТАТЫ ЛАБОРАТОРНЫХ ИССЛЕДОВАНИЙ\nОбщий анализ крови\nГемоглобин 115 г/л\nЛейкоциты 6.2", "лабораторный отчёт"),
            ("BIOCHEM", "Биохимический анализ крови\nАЛТ 20 Ед/л\nАСТ 18 Ед/л", "лабораторный отчёт"),
            ("URINE", "Общий анализ мочи\nБелок — отрицательно\nЛейкоциты 2 в поле зрения", "лабораторный отчёт"),
            ("US", "Протокол ультразвукового исследования\nУЗИ органов брюшной полости\nЗаключение: без особенностей", "заключение УЗИ"),
            ("ECG", "Электрокардиограмма\nЗаключение: синусовый ритм", "заключение ЭКГ"),
            ("XRAY", "Рентгенография органов грудной клетки\nОписание исследования\nЗаключение: без очаговых изменений", "рентгенологическое заключение"),
            ("CT", "Компьютерная томография органов грудной клетки\nЗаключение врача-рентгенолога", "заключение КТ"),
            ("MRI", "Магнитно-резонансная томография головного мозга\nЗаключение", "заключение МРТ"),
            ("SPECIALIST", "Консультация врача-невролога\nЖалобы\nЗаключение специалиста", "консультация специалиста"),
            ("RX", "Рецепт\nRp.: препарат\nСпособ применения", "назначение или рецепт"),
            ("VACCINE", "Сертификат о вакцинации\nНаименование вакцины\nДата прививки", "вакцинальный документ"),
            ("PREGNANCY", "Обменная карта беременной\nСведения о течении беременности", "документ по беременности и родам"),
            ("BIRTH", "История родов\nСведения о родоразрешении", "документ по беременности и родам"),
            ("SURGERY", "Протокол операции\nХод оперативного вмешательства", "операционный протокол"),
            ("ENDOSCOPY", "Протокол ФГДС\nОписание слизистой\nЗаключение", "эндоскопическое заключение"),
            ("PATHOLOGY", "Гистологическое заключение\nМатериал биопсии", "патоморфологическое заключение"),
            ("REFERRAL", "Медицинское направление на консультацию специалиста", "направление"),
            ("CERTIFICATE", "Медицинская справка для предъявления по месту требования", "медицинская справка"),
            ("VISIT", "Протокол первичного приёма врача\nЖалобы\nОсмотр", "протокол осмотра или приёма"),
            ("CARD", "Медицинская карта пациента\nДневник наблюдения", "медицинская карта или наблюдение"),
        ]
        for name, text, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(analyze_document(text)["primary_type"], expected, analyze_document(text))

    def test_topic_mentions_do_not_override_form(self):
        text = """Выписной эпикриз из стационара
Основной диагноз: железодефицитная анемия.
Назначено лечение, рекомендован препарат.
В анализе крови гемоглобин 110 г/л.
"""
        result = analyze_document(text)
        self.assertEqual(result["primary_type"], "выписной эпикриз")
        self.assertIn("лекарства и назначения", result["content_tags"])
        self.assertIn("лабораторные показатели", result["content_tags"])
        self.assertNotIn("назначение или рецепт", result["document_types"])

    def test_mixed_file_and_page_level_types(self):
        text = """--- Страница 1 ---
Выписной эпикриз из стационара
Основной диагноз: анемия.
--- Страница 2 ---
Общий анализ крови
Гемоглобин 115 г/л
Ферритин 16 мкг/л
--- Страница 3 ---
Протокол ультразвукового исследования
УЗИ органов брюшной полости
Заключение: без особенностей
"""
        result = analyze_document(text)
        self.assertEqual(result["primary_type"], "выписной эпикриз")
        self.assertIn("выписной эпикриз", result["document_types"])
        self.assertIn("лабораторный отчёт", result["document_types"])
        self.assertIn("заключение УЗИ", result["document_types"])
        page_map = {item["page"]: item for item in result["page_types"]}
        self.assertEqual(page_map[1]["primary_type"], "выписной эпикриз")
        self.assertEqual(page_map[2]["primary_type"], "лабораторный отчёт")
        self.assertEqual(page_map[3]["primary_type"], "заключение УЗИ")

    def test_ambiguous_or_nonmedical_text_abstains(self):
        for text in ("", "Квитанция об оплате услуги на сумму 500 рублей",
                     "Пациент принимает препарат по назначению врача",
                     "Боль в животе, температура, слабость", "КТ"):
            with self.subTest(text=text):
                result = analyze_document(text)
                self.assertEqual(result["primary_type"], "не определено", result)
                self.assertTrue(result["review_required"])

    def test_page_without_title_does_not_inherit_other_page_class(self):
        text = """--- Страница 1 ---
Выписной эпикриз
Диагноз: ОРВИ
--- Страница 2 ---
Температура 38, кашель, контрольный осмотр.
"""
        result = analyze_document(text)
        page_map = {item["page"]: item for item in result["page_types"]}
        self.assertEqual(page_map[1]["primary_type"], "выписной эпикриз")
        self.assertNotIn("выписной эпикриз", page_map.get(2, {}).get("document_types", []))

    def test_unknown_and_legacy_api(self):
        result = analyze_document("Текст слишком короткий")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(classify_document("УЗИ брюшной полости"), "заключение УЗИ")
        self.assertIn("ферритин", extract_keywords("Ферритин 16 мкг/л"))

    def test_lab_extraction_keeps_page_provenance(self):
        text = "--- Страница 1 ---\nОбщий анализ крови\nГемоглобин 115 г/л\n--- Страница 2 ---\nФерритин 16 мкг/л"
        result = analyze_document(text)
        self.assertTrue(any(x["name"] == "гемоглобин" and x["value"] == "115" and x["page"] == 1 for x in result["lab_results"]))
        self.assertTrue(any(x["name"] == "ферритин" and x["value"] == "16" and x["page"] == 2 for x in result["lab_results"]))


if __name__ == "__main__":
    unittest.main()
