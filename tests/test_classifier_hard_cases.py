import unittest

from AIAnalise import analyze_document


class ClassificationHardCasesTests(unittest.TestCase):
    """Adversarial, synthetic cases: document form vs mentions in body text."""

    def assert_primary(self, text, expected):
        result = analyze_document(text)
        self.assertEqual(result["primary_type"], expected, result)
        return result

    def test_referral_mention_of_imaging_is_not_an_imaging_report(self):
        result = self.assert_primary(
            "Направление на МРТ головного мозга. Просим выполнить исследование.",
            "направление",
        )
        self.assertNotIn("заключение МРТ", result["document_types"])

    def test_recommendation_to_get_ultrasound_is_not_an_ultrasound_report(self):
        self.assert_primary(
            "Врач рекомендовал выполнить УЗИ органов брюшной полости.",
            "не определено",
        )

    def test_real_ultrasound_report_with_routine_referral_metadata_is_classified(self):
        self.assert_primary(
            "УЗИ ВНУТРЕННИХ ОРГАНОВ\\n"
            "Направлен: амбулаторно.\\n"
            "Печень: описание размеров, контуров, структуры и эхогенности.\\n"
            "ЗАКЛЮЧЕНИЕ: исследование выполнено.",
            "заключение УЗИ",
        )

    def test_patient_information_leaflet_does_not_become_an_imaging_report(self):
        self.assert_primary(
            "ПАМЯТКА ДЛЯ ПАЦИЕНТА\\n"
            "Этот информационный лист не является направлением или заключением исследования.\\n"
            "Протокол УЗИ, МРТ или анализы оформляются отдельно после выполнения процедур.",
            "не определено",
        )

    def test_medication_mention_is_not_a_prescription(self):
        result = self.assert_primary(
            "Пациент принимает препарат по ранее выданному назначению врача.",
            "не определено",
        )
        self.assertNotIn("назначение или рецепт", result["document_types"])

    def test_diagnosis_mention_is_not_a_discharge_summary(self):
        self.assert_primary(
            "Диагноз: ОРВИ. Жалобы на насморк и кашель в течение двух дней.",
            "не определено",
        )

    def test_imaging_report_heading_survives_body_noise(self):
        result = self.assert_primary(
            "ЗАКЛЮЧЕНИЕ МРТ\nМагнитно-резонансная томография головного мозга. "
            "Ранее пациенту назначали лекарства, диагноз указан в направлении.",
            "заключение МРТ",
        )
        self.assertIn("заключение МРТ", result["document_types"])

    def test_lab_report_title_is_not_invalidated_by_missing_personal_data(self):
        self.assert_primary(
            "УЧЕБНАЯ ЛАБОРАТОРИЯ\n"
            "РЕЗУЛЬТАТЫ ЛАБОРАТОРНЫХ ИССЛЕДОВАНИЙ\n"
            "Учебный образец; персональные данные отсутствуют.\n"
            "Материал: венозная кровь; дата взятия: 08.10.2026.\n"
            "Общий анализ крови\nГемоглобин: 128 г/л; референсный интервал 120–150.\n"
            "Эритроциты: 4,31 × 10^12/л; лейкоциты: 6,4 × 10^9/л.\n"
            "Тромбоциты: 271 × 10^9/л; гематокрит: 39,8 %.\n"
            "СОЭ: 9 мм/ч. Результаты относятся только к учебному примеру.\n"
            "Дата формирования отчёта: 08.10.2026.",
            "лабораторный отчёт",
        )

    def test_lab_report_with_common_ocr_spacing_noise(self):
        self.assert_primary(
            "РЕЗУЛЬТАТЫ ЛАБОРАТОРНЫХ ИССЛЕДОВАНИЙ\n"
            "Общий анализ крови\nГемоглобин 115 г/л\nЛейкоциты 6.2",
            "лабораторный отчёт",
        )

    def test_unrelated_text_with_medical_terms_abstains(self):
        self.assert_primary(
            "Памятка: приём препарата обсудите с врачом. "
            "При необходимости можно записаться на УЗИ.",
            "не определено",
        )

    def test_bare_modality_acronyms_abstain(self):
        for text in ("УЗИ", "ЭКГ", "МРТ", "КТ", "ФГДС", "рентген"):
            with self.subTest(text=text):
                self.assert_primary(text, "не определено")

    def test_completed_exam_with_missing_conclusion_is_not_a_report(self):
        self.assert_primary(
            "Ранее выполнено УЗИ, заключение отсутствует.",
            "не определено",
        )

    def test_historical_exam_mention_is_not_a_report(self):
        self.assert_primary(
            "В анамнезе выполнена МРТ, сейчас жалоб нет.",
            "не определено",
        )

    def test_passive_referral_for_ct_is_classified_as_referral(self):
        self.assert_primary(
            "Пациент направлен на КТ органов грудной клетки.",
            "направление",
        )

    def test_planned_exam_list_is_not_a_completed_report(self):
        self.assert_primary(
            "План обследования: ЭКГ, УЗИ, анализ крови.",
            "не определено",
        )

    def test_mixed_pages_keep_each_page_class_separate(self):
        result = analyze_document(
            "--- Страница 1 ---\nВыписной эпикриз из стационара\nДиагноз: ОРВИ\n"
            "--- Страница 2 ---\nВрач рекомендовал выполнить УЗИ брюшной полости.\n"
        )
        page_map = {item["page"]: item for item in result["page_types"]}
        self.assertEqual(page_map[1]["primary_type"], "выписной эпикриз")
        self.assertEqual(page_map[2]["primary_type"], "не определено")
        self.assertNotIn("заключение УЗИ", page_map[2]["document_types"])


if __name__ == "__main__":
    unittest.main()

[executed on device: marss1k.fvds.ru (ecc850ae-e012-4a56-b726-1ade67f14bec)]