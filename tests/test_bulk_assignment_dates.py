import os
import unittest

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")

import webapp


class ExplicitDocumentDateTests(unittest.TestCase):
    def test_does_not_treat_date_of_birth_as_document_date(self):
        text = "Дата рождения: 01.02.2020"
        self.assertEqual(webapp.explicit_document_date(text), "")

    def test_extracts_explicit_document_date(self):
        text = "ФИО пациента: Иванов И.И.\nДата исследования: 13.10.2026"
        self.assertEqual(webapp.explicit_document_date(text), "13-10-2026")

    def test_extracts_explicit_date_with_slashes(self):
        text = "Осмотр от 07/09/2025"
        self.assertEqual(webapp.explicit_document_date(text), "07-09-2025")

    def test_invalid_explicit_date_is_ignored(self):
        text = "Дата документа: 31.02.2026"
        self.assertEqual(webapp.explicit_document_date(text), "")


if __name__ == "__main__":
    unittest.main()
