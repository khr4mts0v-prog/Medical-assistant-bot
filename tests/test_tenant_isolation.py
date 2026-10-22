import os
import tempfile
import unittest
from cryptography.fernet import Fernet

TMP = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(TMP.name, "test.sqlite3")
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()

import tenancy
# Other test modules may import tenancy before this module sets its isolated key.
tenancy.FERNET_KEY = os.environ["FERNET_KEY"]
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


    def test_patient_aliases_are_encrypted_and_family_scoped(self):
        database.add_patient(self.a, "Олег", aliases=[
            "Иванов Иван Петрович", "Иванов И.П.", "Иванов И."
        ])
        record = next(row for row in database.patient_records(self.a) if row["name"] == "Олег")
        self.assertEqual(record["aliases"], ["Олег", "Иванов Иван Петрович", "Иванов И.П.", "Иванов И."])
        self.assertTrue(record["aliases_configured"])
        self.assertNotIn("Олег", [row["name"] for row in database.patient_records(self.b)])
        with tenancy.connect() as conn:
            stored = conn.execute(
                "SELECT aliases_enc FROM patients WHERE family_id=? AND name='Олег'", (self.a,)
            ).fetchone()["aliases_enc"]
        self.assertNotIn(b"Ivanov", bytes(stored))
        self.assertNotIn("Иванов".encode("utf-8"), bytes(stored))

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


    def test_document_digest_is_idempotent_at_database_boundary(self):
        args = (
            self.a, "Patient A", "a.pdf", "analysis", "01-01-2026",
            "FamilyA/a.pdf", "FamilyA/a.txt", "same document", ["same"], "same-digest",
        )
        self.assertTrue(database.add_doc(*args))
        self.assertFalse(database.add_doc(*args))
        with tenancy.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM docs WHERE family_id=? AND patient=? AND digest=?",
                (self.a, "Patient A", "same-digest"),
            ).fetchone()["n"]
        self.assertEqual(count, 1)


    def test_sqlite_connection_waits_for_short_write_contention(self):
        with tenancy.connect() as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(timeout, 30000)


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
