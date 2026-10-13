"""Patient matching regression cases. Only synthetic names are used."""
import unittest
from document_metadata import extract_registered_patient


class PatientMatchingTests(unittest.TestCase):
    def test_full_name_maps_to_short_folder_label(self):
        roster = [{"name": "Олег", "aliases": ["Иванов Иван Петрович"]}]
        self.assertEqual(extract_registered_patient("Пациент: Иванов Иван Петрович", roster), "Олег")

    def test_surname_and_two_initials_map_to_registered_patient(self):
        roster = [{"name": "Олег", "aliases": ["Иванов Иван Петрович"]}]
        self.assertEqual(extract_registered_patient("ФИО пациента: Иванов И.П.", roster), "Олег")

    def test_surname_and_one_initial_map_to_registered_patient(self):
        roster = [{"name": "Олег", "aliases": ["Иванов Иван Петрович"]}]
        self.assertEqual(extract_registered_patient("Пациент: Иванов И.", roster), "Олег")

    def test_first_name_is_accepted_in_patient_field(self):
        roster = [{"name": "Маша", "aliases": ["Маша"]}]
        self.assertEqual(extract_registered_patient("Пациент: Маша", roster), "Маша")

    def test_standalone_first_name_is_accepted_in_document_header(self):
        roster = [{"name": "Юля", "aliases": ["Юля"]}]
        self.assertEqual(extract_registered_patient("Юля\nДата заключения: 12.05.2026\nЗаключение", roster), "Юля")

    def test_incidental_first_name_is_not_enough(self):
        roster = [{"name": "Олег", "aliases": ["Олег"]}]
        self.assertIsNone(extract_registered_patient("Врач рассказал Олегу об анализах. Пациент принимает препарат.", roster))

    def test_parent_name_does_not_become_patient(self):
        roster = [{"name": "Маша", "aliases": ["Иванова Анна Сергеевна"]}]
        self.assertIsNone(extract_registered_patient("ФИО матери: Иванова Анна Сергеевна", roster))

    def test_two_people_in_document_are_ambiguous(self):
        roster = [
            {"name": "Олег", "aliases": ["Иванов Иван Петрович"]},
            {"name": "Юля", "aliases": ["Петрова Юлия Сергеевна"]},
        ]
        text = "Иванов Иван Петрович / Петрова Юлия Сергеевна"
        self.assertIsNone(extract_registered_patient(text, roster))

    def test_display_names_remain_distinct_when_full_names_overlap(self):
        roster = [
            {"name": "Саша", "aliases": ["Иванов Александр Сергеевич"]},
            {"name": "Маша", "aliases": ["Иванова Мария Сергеевна"]},
        ]
        self.assertEqual(extract_registered_patient("Пациент: Иванов А.С.", roster), "Саша")


if __name__ == "__main__":
    unittest.main()