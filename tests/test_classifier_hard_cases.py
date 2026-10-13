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

    def test_mixed_pages_keep_each_page_class_separate(self):
        result = analyze_document(
            "--- Страница 1 ---\nВыписной эпикриз из стационара\nДиагноз: ОРВИ\n"
            "--- Страница 2 ---\nВрач рекомендовал выполнить УЗИ брюшной полости.\n"
        )
        page_map = {item["page"]: item for item in result["page_types"]}
        self.assertEqual(page_map[1]["primary_type"], "выписной эпикриз")
        self.assertEqual(page_map[2]["primary_type"], "не определено")
        self.assertNotIn("заключение УЗИ", page_map[2]["document_types"])


    def test_referral_requests_ultrasound_protocol_but_has_no_result(self):
        self.assert_primary(
            "НАПРАВЛЕНИЕ НА МЕДИЦИНСКОЕ ОБСЛЕДОВАНИЕ\n"
            "Вид обследования: ультразвуковое исследование органов брюшной полости.\n"
            "Просим выполнить исследование и выдать протокол с описанием и заключением.\n"
            "Результаты обследования в настоящем документе отсутствуют.",
            "направление",
        )

    def test_visit_note_with_planned_cbc_is_not_lab_report(self):
        self.assert_primary(
            "ПРОТОКОЛ ПЕРВИЧНОГО ПРИЁМА ВРАЧА-ТЕРАПЕВТА\n"
            "Жалобы: утомляемость. Объективно: температура 36,6.\n"
            "План: общий анализ крови; повторная консультация после получения результатов.",
            "протокол осмотра или приёма",
        )

    def test_disclaimer_negation_does_not_make_certificate(self):
        self.assert_primary(
            "ПАМЯТКА ДЛЯ ПАЦИЕНТА\n"
            "При необходимости можно записаться на УЗИ или обсудить МРТ.\n"
            "Данная памятка не является направлением, протоколом исследования, "
            "заключением врача или медицинской справкой.",
            "не определено",
        )

    def test_actual_ultrasound_report_still_classifies_as_report(self):
        self.assert_primary(
            "ПРОТОКОЛ УЛЬТРАЗВУКОВОГО ИССЛЕДОВАНИЯ\n"
            "Исследование выполнено. Печень без особенностей.\n"
            "Заключение: эхографических признаков патологии не выявлено.",
            "заключение УЗИ",
        )

    def test_referral_to_mri_not_report_despite_requested_protocol(self):
        result = self.assert_primary(
            "МЕДИЦИНСКОЕ НАПРАВЛЕНИЕ на МРТ головного мозга. "
            "Просим провести исследование и направить протокол лечащему врачу.",
            "направление",
        )
        self.assertNotIn("заключение МРТ", result["document_types"])

    def test_negative_mentions_of_document_types_do_not_win(self):
        self.assert_primary(
            "ПАМЯТКА. Это не выписной эпикриз и не медицинская справка. "
            "Документ не содержит результатов обследования.",
            "не определено",
        )


    def test_missing_character_in_mri_heading_is_tolerated(self):
        self.assert_primary(
            "ЗАКЛЮЧЕНИ МРТ\n"
            "Магнитно-резонансная томография головного мозга. "
            "Очаговых изменений не выявлено.",
            "заключение МРТ",
        )

    def test_missing_character_in_lab_heading_is_tolerated(self):
        self.assert_primary(
            "РЕЗУЛТАТЫ ЛАБОРАТОРНЫХ ИССЛЕДОВАНИЙ\n"
            "Показатель: 12,4; референсный интервал: 4,0–15,0.",
            "лабораторный отчёт",
        )

    def test_inserted_character_in_consultation_heading_is_tolerated(self):
        self.assert_primary(
            "КОНСУЛЬТАЦИЯ ВРАЧА-НЕВРОЛОГАА\n"
            "Жалобы: головная боль. Заключение специалиста прилагается.",
            "консультация специалиста",
        )

    def test_typo_tolerance_does_not_search_entire_body_for_headings(self):
        self.assert_primary(
            "ПАМЯТКА ДЛЯ ПАЦИЕНТА\n"
            "При необходимости обсудите с врачом заключени МРТ и результаты обследования.",
            "не определено",
        )

    def test_clean_heading_still_classifies_after_typo_support_added(self):
        self.assert_primary(
            "ЗАКЛЮЧЕНИЕ МРТ\n"
            "Очаговых изменений вещества головного мозга не выявлено.",
            "заключение МРТ",
        )


if __name__ == "__main__":
    unittest.main()
