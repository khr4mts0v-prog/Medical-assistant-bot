"""First-pass holdout cases authored after the main corpus reached 100%.
These are synthetic challenge texts, not patient records. Do not use them to
claim real-world accuracy; failures should be reviewed before changing rules.
"""
import unittest

from AIAnalise import classify_document


HOLDOUT_CASES = [
    (
        "holdout_lab_alt_heading",
        "лабораторный отчёт",
        "БИОХИМИЧЕСКИЙ АНАЛИЗ КРОВИ\nАЛТ 22 Ед/л; АСТ 19 Ед/л; билирубин общий 12 мкмоль/л.",
    ),
    (
        "holdout_ecg_abbreviation",
        "заключение ЭКГ",
        "ЭКГ в 12 отведениях\nРитм синусовый. Электрическая ось сердца без отклонений. Заключение врача функциональной диагностики.",
    ),
    (
        "holdout_ct_phrase_order",
        "заключение КТ",
        "Компьютерная томография органов грудной клетки\nОписание: лёгочная ткань без очаговых изменений. Итог: данных за острый процесс не получено.",
    ),
    (
        "holdout_mri_report",
        "заключение МРТ",
        "МАГНИТНО-РЕЗОНАНСНАЯ ТОМОГРАФИЯ ПОЯСНИЧНОГО ОТДЕЛА\nОписание исследования и заключение врача-рентгенолога.",
    ),
    (
        "holdout_ultrasound_alternate",
        "заключение УЗИ",
        "Ультразвуковое исследование щитовидной железы\nПравая доля ... Левая доля ... Заключение сонолога: эхографическая картина описана.",
    ),
    (
        "holdout_endoscopy",
        "эндоскопическое заключение",
        "ФГДС: протокол эзофагогастродуоденоскопии\nПищевод проходим. Желудок осмотрен. Заключение эндоскописта приведено ниже.",
    ),
    (
        "holdout_pathology_word_order",
        "патоморфологическое заключение",
        "РЕЗУЛЬТАТ ГИСТОЛОГИЧЕСКОГО ИССЛЕДОВАНИЯ\nМатериал: биоптат. Микроскопическое описание. Морфологический диагноз.",
    ),
    (
        "holdout_prescription_without_form_number",
        "назначение или рецепт",
        "РЕЦЕПТ\nRp.: препарат условный\nD.t.d. № 1\nS. Согласно назначению врача. Подпись и дата.",
    ),
    (
        "holdout_specialist_consult",
        "консультация специалиста",
        "ЗАКЛЮЧЕНИЕ ВРАЧА-НЕВРОЛОГА\nЖалобы, анамнез, неврологический статус. Рекомендации по дальнейшему наблюдению.",
    ),
    (
        "holdout_referral_not_report",
        "направление",
        "НАПРАВЛЕНИЕ\nПросим выполнить эхокардиографию и передать протокол лечащему врачу. Исследование ещё не проводилось.",
    ),
    (
        "holdout_missing_report",
        "не определено",
        "Выполненное ранее исследование упомянуто в анамнезе. Сам протокол и заключение в данном файле отсутствуют.",
    ),
    (
        "holdout_ambiguous_medication_mention",
        "не определено",
        "В памятке указано: лекарства следует принимать только по назначению врача. Нового назначения или рецепта этот текст не содержит.",
    ),
]


class ClassifierHoldoutRound1Tests(unittest.TestCase):
    def test_holdout_cases(self):
        mismatches = []
        for case_id, expected, text in HOLDOUT_CASES:
            with self.subTest(case=case_id):
                actual = classify_document(text)
                if actual != expected:
                    mismatches.append((case_id, expected, actual))
        self.assertFalse(mismatches, f"Holdout mismatches: {mismatches}")


if __name__ == "__main__":
    unittest.main()
