import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.TemporaryDirectory()
os.environ["LOCAL_STORAGE_PATH"] = os.path.join(TMP.name, "documents")

import local_storage

class LocalStorageTests(unittest.TestCase):
    def test_files_are_separated_by_family_and_patient(self):
        src = Path(TMP.name) / "sample.pdf"
        src.write_bytes(b"%PDF-test")
        a = local_storage.save_file(1, "Patient A", "doc.pdf", src)
        b = local_storage.save_file(2, "Patient A", "doc.pdf", src)
        c = local_storage.save_file(1, "Patient B", "doc.pdf", src)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a.read_bytes(), b"%PDF-test")

    def test_existing_file_is_not_overwritten(self):
        src = Path(TMP.name) / "sample.pdf"
        src.write_bytes(b"one")
        target = local_storage.save_file(3, "Patient C", "doc.pdf", src)
        src.write_bytes(b"two")
        with self.assertRaises(FileExistsError):
            local_storage.save_file(3, "Patient C", "doc.pdf", src)
        self.assertEqual(target.read_bytes(), b"one")

    def test_invalid_family_and_filename_are_rejected(self):
        src = Path(TMP.name) / "sample.pdf"
        src.write_bytes(b"sample")
        with self.assertRaises(ValueError):
            local_storage.document_dir(-1, "Patient A")
        with self.assertRaises(ValueError):
            local_storage.save_file(4, "Patient A", "../outside.pdf", src)

if __name__ == "__main__":
    unittest.main()
