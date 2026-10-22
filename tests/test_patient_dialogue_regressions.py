'''Regression tests for consultation follow-up detection.'''
import unittest

import assistant_routes


class PatientDialogueRegressionTests(unittest.TestCase):
    def test_followup_references_consultation_without_name(self):
        question = "Дружище, по этой консультации кратко — вывод. Что назначено, какие рекомендации, что делать?"
        self.assertTrue(assistant_routes._looks_like_contextual_medical_followup(question))

    def test_followup_references_previous_report(self):
        for question in (
            "По этому заключению какие рекомендации?",
            "Что назначено по предыдущей консультации?",
            "Какой итог по этой выписке?",
        ):
            with self.subTest(question=question):
                self.assertTrue(assistant_routes._looks_like_contextual_medical_followup(question))

    def test_pronoun_based_allergy_memory_command_is_a_followup(self):
        question = "Добавь ему в память аллергию на кошек и собак, на контакт. Реакция — чешется борода и глаза"
        self.assertTrue(assistant_routes._looks_like_contextual_medical_followup(question))

    def test_explicit_allergy_memory_command_creates_reviewable_fact(self):
        question = "Добавь ему в память аллергию на кошек и собак, на контакт. Реакция — чешется борода и глаза"
        facts = assistant_routes._extract_explicit_memory_facts(question)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["memory_key"], "allergy")
        self.assertEqual(facts[0]["category"], "symptom")
        self.assertIn("кошек и собак", facts[0]["text"])
        self.assertIn("чешется борода и глаза", facts[0]["text"])

    def test_allergy_is_not_extracted_from_hypothetical_question(self):
        question = "Можно ли добавить аллергию на кошек в память?"
        self.assertEqual(assistant_routes._extract_explicit_memory_facts(question), [])

    def test_bare_patient_switch_inherits_previous_topic(self):
        self.assertTrue(assistant_routes._looks_like_patient_topic_ellipsis("А теперь по Саше", ["Саша"]))
        self.assertTrue(assistant_routes._looks_like_patient_topic_ellipsis("Теперь по Олегу", ["Олег"]))
        # A request that already specifies a medical topic should search it directly.
        self.assertFalse(assistant_routes._looks_like_patient_topic_ellipsis("А теперь по Саше по крови", ["Саша"]))

    def test_duplicate_custom_alias_is_ambiguous_without_distinguishing_name(self):
        records = [
            {"name": "Дмитрий Иванов", "aliases": ["Дмитрий Иванов", "Димка"]},
            {"name": "Денис Петров", "aliases": ["Денис Петров", "Димка"]},
        ]
        self.assertTrue(assistant_routes._has_ambiguous_custom_alias_reference(records, "Сравни документы Димка"))
        self.assertTrue(assistant_routes._has_ambiguous_custom_alias_reference(records, "Сравни документы Димка и Олега"))
        self.assertFalse(assistant_routes._has_ambiguous_custom_alias_reference(records, "Сравни документы Димка Иванов"))
        self.assertFalse(assistant_routes._has_ambiguous_custom_alias_reference(records, "Сравни документы Дмитрия Иванова и Дениса Петрова"))

    def test_standalone_general_definition_is_not_a_followup(self):
        self.assertFalse(assistant_routes._looks_like_contextual_medical_followup("Что такое ферритин?"))


if __name__ == "__main__":
    unittest.main()
