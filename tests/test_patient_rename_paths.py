"""Regression tests for keeping indexed document paths in sync with patient renames."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")

import database
import tenancy
from cryptography.fernet import Fernet


class PatientRenamePathTests(unittest.TestCase):
    def test_rename_updates_document_paths_only_for_target_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "archive.sqlite3"
            key = Fernet.generate_key().decode("ascii")
            with (
                patch.object(tenancy, "DB_PATH", db_path),
                patch.object(tenancy, "FERNET_KEY", key),
                patch.object(database, "_refresh_patient_memory"),
            ):
                database.init()
                family_id = tenancy.create_family("Family A", 101)
                other_family_id = tenancy.create_family("Family B", 202)
                database.add_patient(family_id, "Саша")
                database.add_patient(other_family_id, "Саша")

                old_prefix = str(Path(tmp) / "family_1" / "Саша") + os.sep
                new_prefix = str(Path(tmp) / "family_1" / "Александр") + os.sep
                other_prefix = str(Path(tmp) / "family_2" / "Саша") + os.sep
                database.add_doc(
                    family_id, "Саша", "analysis.pdf", "анализ", "20-10-2026",
                    old_prefix + "analysis.pdf", old_prefix + "analysis.txt",
                    "тестовый текст", [], "digest-family-a",
                )
                database.add_doc(
                    other_family_id, "Саша", "analysis.pdf", "анализ", "20-10-2026",
                    other_prefix + "analysis.pdf", other_prefix + "analysis.txt",
                    "другой архив", [], "digest-family-b",
                )

                database.update_patient_profile(
                    family_id, "Саша", "Александр",
                    old_storage_prefix=old_prefix,
                    new_storage_prefix=new_prefix,
                )

                with tenancy.connect() as conn:
                    target = conn.execute(
                        "SELECT patient, remote, ocr_remote FROM docs WHERE family_id=?",
                        (family_id,),
                    ).fetchone()
                    other = conn.execute(
                        "SELECT patient, remote, ocr_remote FROM docs WHERE family_id=?",
                        (other_family_id,),
                    ).fetchone()

                self.assertEqual(target["patient"], "Александр")
                self.assertEqual(target["remote"], new_prefix + "analysis.pdf")
                self.assertEqual(target["ocr_remote"], new_prefix + "analysis.txt")
                self.assertEqual(other["patient"], "Саша")
                self.assertEqual(other["remote"], other_prefix + "analysis.pdf")
                self.assertEqual(other["ocr_remote"], other_prefix + "analysis.txt")


if __name__ == "__main__":
    unittest.main()
