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

    def test_standalone_general_definition_is_not_a_followup(self):
        self.assertFalse(assistant_routes._looks_like_contextual_medical_followup("Что такое ферритин?"))


if __name__ == "__main__":
    unittest.main()
