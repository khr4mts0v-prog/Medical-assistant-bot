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


if __name__ == "__main__":
    unittest.main()
