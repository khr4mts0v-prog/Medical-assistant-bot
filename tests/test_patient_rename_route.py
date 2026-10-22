"""Regression tests for patient rename failure handling."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")

import webapp
import local_storage
from fastapi import HTTPException


class PatientRenameRouteTests(unittest.TestCase):
    def test_database_failure_restores_original_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            old_dir = root / "family_7" / "Саша"
            old_dir.mkdir(parents=True)
            original = old_dir / "analysis.pdf"
            original.write_bytes(b"synthetic test document")
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp, "STORAGE_BACKEND", "local"),
                patch.object(webapp, "family"),
                patch.object(webapp.db, "update_patient_profile", side_effect=RuntimeError("synthetic failure")),
            ):
                with self.assertRaises(HTTPException) as caught:
                    webapp.save_patient_page(7, "Саша", "Александр", "", "", uid=123)
            self.assertEqual(caught.exception.status_code, 500)
            self.assertTrue(original.is_file())
            self.assertEqual(original.read_bytes(), b"synthetic test document")
            self.assertFalse((root / "family_7" / "Александр").exists())

    def test_existing_destination_blocks_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            family_dir = root / "family_7"
            old_dir = family_dir / "Саша"
            new_dir = family_dir / "Александр"
            old_dir.mkdir(parents=True)
            new_dir.mkdir()
            original = old_dir / "analysis.pdf"
            original.write_bytes(b"synthetic test document")
            marker = new_dir / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp, "STORAGE_BACKEND", "local"),
                patch.object(webapp, "family"),
                patch.object(webapp.db, "update_patient_profile") as update_profile,
            ):
                with self.assertRaises(HTTPException) as caught:
                    webapp.save_patient_page(7, "Саша", "Александр", "", "", uid=123)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertTrue(original.is_file())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            update_profile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
