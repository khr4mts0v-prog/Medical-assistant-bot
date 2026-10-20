import unittest

from document_references import discover_referenced_documents


class ReferencedDocumentDiscoveryTests(unittest.TestCase):
    def test_finds_explicitly_referenced_document_by_specialty(self):
        source = {
            "id": 1,
            "name": "УЗИ",
            "date": "2026-01-10",
            "text": "В заключении УЗИ упомянуто заключение эпилептолога.",
        }
        companion = {
            "id": 2,
            "name": "Заключение эпилептолога",
            "kind": "консультация специалиста",
            "date": "2026-01-12",
            "text": "Осмотр эпилептолога. Рекомендации.",
        }
        result = discover_referenced_documents([source], [source, companion])
        self.assertEqual([row["id"] for row in result["found_documents"]], [2])
        self.assertEqual(result["missing_required"], [])

    def test_required_missing_reference_is_reported(self):
        source = {
            "id": 10,
            "name": "Протокол обследования",
            "date": "2026-02-01",
            "text": "Для интерпретации результатов необходимо заключение эпилептолога.",
        }
        result = discover_referenced_documents([source], [source])
        self.assertEqual(result["found_documents"], [])
        self.assertEqual(len(result["missing_required"]), 1)
        self.assertEqual(result["missing_required"][0]["source"]["document_id"], 10)
        self.assertEqual(result["missing_required"][0]["reason"], "explicit_reference_required_for_interpretation")

    def test_optional_missing_reference_does_not_trigger_request(self):
        source = {
            "id": 20,
            "name": "УЗИ",
            "date": "2026-03-01",
            "text": "В заключении упомянуто заключение эпилептолога.",
        }
        result = discover_referenced_documents([source], [source])
        self.assertEqual(result["found_documents"], [])
        self.assertEqual(result["missing_required"], [])

    def test_never_returns_documents_from_outside_supplied_patient_rows(self):
        source = {
            "id": 1,
            "name": "УЗИ",
            "text": "Сопоставить с заключением эпилептолога.",
        }
        # The candidate list is explicitly the selected patient's documents.
        other = {
            "id": 99,
            "name": "Заключение эпилептолога",
            "text": "Эпилептолог",
        }
        result = discover_referenced_documents([source], [source])
        self.assertNotIn(other, result["found_documents"])
        self.assertEqual(len(result["missing_required"]), 1)


if __name__ == "__main__":
    unittest.main()
