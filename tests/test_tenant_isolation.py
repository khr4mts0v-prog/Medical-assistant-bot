import os
import tempfile
import unittest
from cryptography.fernet import Fernet

TMP = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(TMP.name, "test.sqlite3")
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

import tenancy
import database

class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        tenancy.init()
        self.a = tenancy.create_family("Family A", 101)
        self.b = tenancy.create_family("Family B", 202)
        database.add_patient(self.a, "Patient A")
        database.add_patient(self.b, "Patient B")

    def test_patient_lists_are_scoped(self):
        self.assertEqual(database.patients(self.a), ["Patient A"])
        self.assertEqual(database.patients(self.b), ["Patient B"])

    def test_document_search_is_scoped_and_text_encrypted(self):
        database.add_doc(self.a, "Patient A", "a.pdf", "analysis", "01-01-2026",
                         "FamilyA/a.pdf", "FamilyA/a.txt", "secret alpha", ["alpha"], "digest-a")
        database.add_doc(self.b, "Patient B", "b.pdf", "analysis", "01-01-2026",
                         "FamilyB/b.pdf", "FamilyB/b.txt", "secret beta", ["beta"], "digest-b")
        self.assertEqual(len(database.search(self.a, "Patient A", "alpha")), 1)
        self.assertEqual(database.search(self.a, "Patient A", "beta"), [])
        self.assertEqual(database.context(self.a, "Patient A", "beta"), "")
        with tenancy.connect() as conn:
            stored=conn.execute("SELECT text FROM docs WHERE family_id=?",(self.a,)).fetchone()["text"]
        self.assertNotIn(b"secret alpha", bytes(stored))

    def test_membership_is_family_specific(self):
        self.assertEqual(tenancy.role_for_user(self.a, 101), "owner")
        self.assertIsNone(tenancy.role_for_user(self.b, 101))
        with self.assertRaises(PermissionError):
            tenancy.add_member(self.b, 303, actor_id=101)

    def test_token_is_encrypted_and_roundtrips(self):
        token = "secret-yandex-token"
        tenancy.save_yadisk_token(self.a, token, "test account")
        self.assertEqual(tenancy.get_yadisk_token(self.a), token)
        family = tenancy.get_family(self.a)
        self.assertNotIn(token.encode(), bytes(family["yadisk_token_enc"]))

if __name__ == "__main__":
    unittest.main()
