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





class ClassificationTaxonomyTests(unittest.TestCase):
    def test_every_leaf_type_has_one_parent_category(self):
        from AIAnalise import DOCUMENT_TYPE_RULES, DOCUMENT_TAXONOMY
        self.assertEqual(set(DOCUMENT_TYPE_RULES), set(DOCUMENT_TAXONOMY))
        self.assertEqual(len(DOCUMENT_TAXONOMY), len(DOCUMENT_TYPE_RULES))

    def test_primary_taxonomy_is_exposed_without_changing_legacy_leaf_label(self):
        result = analyze_document("Протокол УЗИ органов малого таза. Заключение: без особенностей.")
        self.assertEqual(result["primary_type"], "заключение УЗИ")
        self.assertEqual(result["primary_category"], "Инструментальная диагностика")
        self.assertEqual(result["taxonomy_path"], ["Инструментальная диагностика", "заключение УЗИ"])
        self.assertEqual(result["page_types"][0]["primary_category"], "Инструментальная диагностика")


class DocumentMetadataTests(unittest.TestCase):
    def test_conclusion_date_outranks_study_date(self):
        from document_metadata import extract_document_date
        text = "Дата исследования: 10.05.2026\nДата заключения: 12.05.2026"
        self.assertEqual(extract_document_date(text), "12-05-2026")

    def test_issue_date_outranks_study_date(self):
        from document_metadata import extract_document_date
        text = "Дата выдачи: 12.05.2026\nДата исследования: 10.05.2026"
        self.assertEqual(extract_document_date(text), "12-05-2026")

    def test_study_date_alone_is_not_document_date(self):
        from document_metadata import extract_document_date
        self.assertIsNone(extract_document_date("Дата исследования: 10.05.2026"))

    def test_generic_date_after_study_date_is_not_suppressed(self):
        from document_metadata import extract_document_date
        text = "Дата исследования: 10.05.2026\\nДата: 12.05.2026"
        self.assertEqual(extract_document_date(text), "12-05-2026")


    def test_birth_date_alone_is_not_document_date(self):
        from document_metadata import extract_document_date
        self.assertIsNone(extract_document_date("Дата рождения: 05.04.2019"))

    def test_multiple_unlabelled_dates_are_ambiguous(self):
        from document_metadata import extract_document_date
        self.assertIsNone(extract_document_date("12.05.2026; 13.05.2026"))

    def test_single_unlabelled_date_is_accepted(self):
        from document_metadata import extract_document_date
        self.assertEqual(extract_document_date("Протокол. 12.05.2026"), "12-05-2026")

    def test_invalid_date_is_rejected(self):
        from document_metadata import extract_document_date
        self.assertIsNone(extract_document_date("Дата заключения: 32.05.2026"))


    def test_report_result_date_outranks_execution_date(self):
        from document_metadata import extract_document_date
        text = "Исследование проведено 10.05.2026\\nДата результата: 12.05.2026"
        self.assertEqual(extract_document_date(text), "12-05-2026")

    def test_unique_date_of_completed_study_is_not_assumed_to_be_report_date(self):
        from document_metadata import extract_document_date
        text = "УЗИ проведено 10.05.2026. Результат выдан отдельно."
        self.assertIsNone(extract_document_date(text))

    def test_ct_title_includes_anatomical_region(self):
        from document_metadata import infer_document_title
        self.assertEqual(infer_document_title("Протокол КТ поясничного отдела позвоночника", "заключение КТ"),
                         "КТ — поясничного отдела")

    def test_mri_title_includes_anatomical_region(self):
        from document_metadata import infer_document_title
        self.assertEqual(infer_document_title("Протокол МРТ головного мозга", "заключение МРТ"),
                         "МРТ — головного мозга")

    def test_endoscopy_title_is_specific(self):
        from document_metadata import infer_document_title
        self.assertEqual(infer_document_title("Протокол колоноскопии. Заключение", "эндоскопическое заключение"),
                         "Колоноскопия")

    def test_mycology_laboratory_report_and_report_creation_date(self):
        from AIAnalise import analyze_document, classify_document
        from document_metadata import extract_document_date, infer_document_title

        text = """ПАЦИЕНТ ТЕСТОВЫЙ
Заказ №: 12345
Зарегистрирован: 04.10.2026 17:06:52
Исследование кожи и ногтевых пластинок на поверхностные микозы (образец ткани)
Ногти (пр. нога), валидация 06.10.2026 19:44:48
Метод: Микроскопия
Грибы: мицелий — не обнаружен
Грибы: псевдомицелий — не обнаружен
Грибы: споры — не обнаружены
Грибы: дрожжеподобные клетки — не обнаружены
Отчет создан: 06.10.2026 19:44:49
Страница 1 из 1"""
        result = analyze_document(text)
        self.assertEqual(classify_document(text), "лабораторный отчёт")
        self.assertEqual(result["confidence"], "high")
        self.assertFalse(result["review_required"])
        self.assertEqual(extract_document_date(text), "06-10-2026")
        self.assertEqual(infer_document_title(text, result["primary_type"]), "Анализ на поверхностные микозы")

    def test_registered_patient_full_name(self):
        from document_metadata import extract_registered_patient
        roster = ["Иванов Иван Иванович", "Петров Пётр Петрович"]
        self.assertEqual(extract_registered_patient("Пациент: Иванов Иван Иванович", roster), roster[0])

    def test_multiple_patient_names_are_ambiguous(self):
        from document_metadata import extract_registered_patient
        roster = ["Иванов Иван Иванович", "Петров Пётр Петрович"]
        self.assertIsNone(extract_registered_patient("Иванов Иван Иванович / Петров Пётр Петрович", roster))

    def test_parent_name_is_not_matched_as_patient(self):
        from document_metadata import extract_registered_patient
        roster = ["Иванова Анна Сергеевна"]
        self.assertIsNone(extract_registered_patient("ФИО матери: Иванова Анна Сергеевна", roster))

    def test_ultrasound_title_contains_region(self):
        from document_metadata import infer_document_title
        self.assertEqual(infer_document_title("Протокол УЗИ органов малого таза", "заключение УЗИ"), "УЗИ малого таза")

    def test_filename_is_date_first_and_collision_resistant(self):
        from document_metadata import format_archive_filename
        self.assertEqual(
            format_archive_filename("12-05-2026", "УЗИ малого таза", "pdf", "abcdef1234"),
            "12-05-2026 УЗИ малого таза — abcdef12.pdf",
        )


if __name__ == "__main__":
    unittest.main()