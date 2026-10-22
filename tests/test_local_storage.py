import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory()
os.environ["LOCAL_STORAGE_PATH"] = os.path.join(TMP.name, "documents")

import local_storage
# Other test modules may import local_storage before this test sets its isolated path.
local_storage.DATA_ROOT = Path(os.environ["LOCAL_STORAGE_PATH"]).resolve()

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

    def test_partial_file_is_removed_when_source_read_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            source = Path(tmp) / "source.bin"
            source.write_bytes(b"x" * (1024 * 1024 + 1))
            real_open = Path.open

            class Reader:
                def __init__(self, file):
                    self.file = file
                    self.calls = 0
                def __enter__(self):
                    self.file.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.file.__exit__(*args)
                def read(self, size=-1):
                    self.calls += 1
                    if self.calls > 1:
                        raise OSError("synthetic read failure")
                    return self.file.read(size)

            def open_path(path, mode="r", *args, **kwargs):
                handle = real_open(path, mode, *args, **kwargs)
                return Reader(handle) if path == source and mode == "rb" else handle

            with patch.object(local_storage, "DATA_ROOT", root.resolve()):
                with patch.object(Path, "open", autospec=True, side_effect=open_path):
                    with self.assertRaisesRegex(OSError, "synthetic read failure"):
                        local_storage.save_file(1, "Sasha", "original.bin", source)
                self.assertEqual(list((root / "family_1" / "Sasha").iterdir()), [])

if __name__ == "__main__":
    unittest.main()
