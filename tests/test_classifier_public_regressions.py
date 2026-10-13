import unittest

from AIAnalise import analyze_document


class PublicClassifierRegressionTests(unittest.TestCase):
    def test_generic_laboratory_form_with_structured_result(self):
        text = """РЕЗУЛЬТАТЫ ВЫПОЛНЕННЫХ ИССЛЕДОВАНИЙ
Исследование: 25-ОН витамин D.
Результат: 45,00 нг/мл.
Референсные значения: 30–80 — оптимальный уровень."""
        self.assertEqual(analyze_document(text)["primary_type"], "лабораторный отчёт")

    def test_ultrasound_title_with_conclusion_section(self):
        text = """УЗИ ВНУТРЕННИХ ОРГАНОВ
Брюшная полость.
Печень: описание размеров, контуров, структуры и эхогенности.
ЗАКЛЮЧЕНИЕ:
Ультразвуковое исследование внутренних органов."""
        self.assertEqual(analyze_document(text)["primary_type"], "заключение УЗИ")

    def test_parenthetical_discharge_epicrisis_heading(self):
        text = """ВЫПИСНОЙ (ПЕРЕВОДНОЙ) ЭПИКРИЗ
Наименование медицинской организации.
Наименование отделения. Номер медицинской карты.
Сведения о пациенте: ФИО, дата рождения, пол.
Поступил в стационар. Период нахождения в стационаре.
Исход госпитализации: выписан.
Клинический диагноз: основной диагноз, осложнения, сопутствующие заболевания.
Проведённое лечение. Состояние при выписке. Рекомендации."""
        self.assertEqual(analyze_document(text)["primary_type"], "выписной эпикриз")

    def test_referral_mentioning_ultrasound_is_not_ultrasound_report(self):
        text = """Направление на УЗИ органов брюшной полости
Просим выполнить исследование.
Заключение: предоставить после проведения исследования."""
        self.assertEqual(analyze_document(text)["primary_type"], "направление")


if __name__ == "__main__":
    unittest.main()
