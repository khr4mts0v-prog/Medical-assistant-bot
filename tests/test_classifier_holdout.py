"""Independent synthetic holdout checks for classifier generalization.

These examples were authored separately from the benchmark fixtures. They are
not patient records and are intentionally not copied from existing corpus files.
The suite emphasizes unseen wording and negative controls.
"""
import unittest

from AIAnalise import analyze_document


class ClassifierHoldoutTests(unittest.TestCase):
    def assert_primary(self, text, expected):
        result = analyze_document(text)
        self.assertEqual(result["primary_type"], expected, result)
        return result

    # Positive examples: alternate wording and layouts for known document forms.
    def test_holdout_lab_report_alternate_heading(self):
        self.assert_primary(
            "Лабораторный протокол\nОбщий анализ крови\nЭритроциты 4,5 x10^12/л\n"
            "Гемоглобин 132 г/л\nТромбоциты 245 x10^9/л",
            "лабораторный отчёт",
        )

    def test_holdout_biochemistry_report(self):
        self.assert_primary(
            "Результаты биохимического анализа\nКреатинин 78 мкмоль/л\n"
            "Билирубин общий 11 мкмоль/л\nРеференсные значения указаны в таблице",
            "лабораторный отчёт",
        )

    def test_holdout_ultrasound_alternate_heading(self):
        self.assert_primary(
            "Протокол ультразвукового исследования щитовидной железы\n"
            "Правая доля: размеры приведены в описании. Эхоструктура однородная.\n"
            "Заключение: эхографические признаки без особенностей.",
            "заключение УЗИ",
        )

    def test_holdout_ecg_report(self):
        self.assert_primary(
            "Протокол электрокардиограммы\nРитм синусовый. ЧСС 76 в минуту.\n"
            "Электрическая ось сердца без отклонения. Заключение врача.",
            "заключение ЭКГ",
        )

    def test_holdout_ct_report(self):
        self.assert_primary(
            "Заключение по компьютерной томографии\nИсследование органов грудной клетки.\n"
            "Описание структур представлено ниже. Итоговое заключение радиолога.",
            "заключение КТ",
        )

    def test_holdout_mri_report(self):
        self.assert_primary(
            "Протокол МРТ\nМагнитно-резонансная томография поясничного отдела.\n"
            "Описание сигнала и межпозвонковых дисков. Заключение специалиста.",
            "заключение МРТ",
        )

    def test_holdout_endoscopy_report(self):
        self.assert_primary(
            "Заключение гастроскопии\nПищевод проходим. Слизистая желудка осмотрена.\n"
            "Двенадцатиперстная кишка без описанных изменений.",
            "эндоскопическое заключение",
        )

    def test_holdout_pathology_report(self):
        self.assert_primary(
            "Гистологическое заключение\nМатериал исследован микроскопически.\n"
            "Морфологическое описание и итог патоморфолога.",
            "патоморфологическое заключение",
        )

    def test_holdout_specialist_consultation(self):
        self.assert_primary(
            "Консультация врача-невролога\nЖалобы и анамнез собраны.\n"
            "Объективный статус, заключение специалиста и план наблюдения.",
            "консультация специалиста",
        )

    def test_holdout_medication_order(self):
        self.assert_primary(
            "Лист назначений лекарственных препаратов\nПрепарат А — по схеме врача.\n"
            "Дата назначения и подпись медицинского работника.",
            "назначение или рецепт",
        )

    def test_holdout_referral_for_analysis(self):
        self.assert_primary(
            "Медицинское направление\nНаправление на анализы перед плановым обследованием.\n"
            "Дата и подпись направившего врача.",
            "направление",
        )

    def test_holdout_medical_certificate(self):
        self.assert_primary(
            "Медицинская справка для предъявления по месту требования\n"
            "Выдана после осмотра медицинским работником.",
            "медицинская справка",
        )

    # Negative controls: medical terms are mentioned, but no such document exists.
    def test_holdout_recommendation_is_not_completed_ultrasound(self):
        self.assert_primary(
            "Врач рекомендовал записаться на ультразвуковое исследование позже. "
            "Протокол пока не оформлялся.",
            "не определено",
        )

    def test_holdout_historical_ct_is_not_report(self):
        self.assert_primary(
            "В анамнезе указана компьютерная томография несколько лет назад. "
            "Текущего заключения нет.",
            "не определено",
        )

    def test_holdout_lab_values_without_report_context_abstain(self):
        self.assert_primary(
            "В переписке упомянуты гемоглобин 132 и креатинин 78. "
            "Это заметка для подготовки к визиту, не лабораторный бланк.",
            "не определено",
        )

    def test_holdout_medication_history_is_not_prescription(self):
        self.assert_primary(
            "Пациент сообщил, что раньше принимал препарат по назначению. "
            "Новый рецепт и лист назначений не выдавались.",
            "не определено",
        )

    def test_holdout_document_checklist_abstains(self):
        self.assert_primary(
            "Для приёма подготовить: старую выписку, ЭКГ, УЗИ и анализы. "
            "Это список документов, а не результаты исследований.",
            "не определено",
        )

    def test_holdout_bare_specialty_and_modality_abstain(self):
        for text in ("Невролог", "ЭКГ", "КТ", "анализ крови"):
            with self.subTest(text=text):
                self.assert_primary(text, "не определено")

    def test_holdout_information_leaflet_abstains(self):
        self.assert_primary(
            "ИНФОРМАЦИОННЫЙ ЛИСТ\nВ этом материале объясняется, что такое МРТ. "
            "Само исследование не проводилось, заключение не выдавалось.",
            "не определено",
        )

    def test_holdout_missing_pathology_result_abstains(self):
        self.assert_primary(
            "В направлении указано: гистологическое заключение будет готово позднее. "
            "Результат исследования в документ не включён.",
            "не определено",
        )

    def test_holdout_future_mri_appointment_is_not_report(self):
        self.assert_primary(
            "Врач сказал принести заключение МРТ, но в сообщении обсуждается только дата "
            "записи на исследование. Сканирование ещё не проводилось и заключение не выдавалось.",
            "не определено",
        )

    def test_holdout_historical_medication_is_not_new_prescription(self):
        self.assert_primary(
            "Пациент вспоминает прежнюю схему лечения и препарат, который принимал прошлой зимой. "
            "Нового назначения, рецептурного бланка или листа терапии в сообщении нет.",
            "не определено",
        )


if __name__ == "__main__":
    unittest.main()
