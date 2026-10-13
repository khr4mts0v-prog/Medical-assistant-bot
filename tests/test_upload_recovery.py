import tempfile
import unittest
from pathlib import Path

from upload_recovery import cleanup_unqueued_upload


class UploadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.staged = self.root / "upload.enc"
        self.sidecar = self.root / "upload.pending"
        self.staged.write_bytes(b"encrypted-stage")
        self.sidecar.write_bytes(b"encrypted-metadata")

    def tearDown(self):
        self.tmp.cleanup()

    def test_queued_upload_artifacts_are_preserved_after_error(self):
        cleaned = cleanup_unqueued_upload(self.staged, self.sidecar, queued=True)
        self.assertFalse(cleaned)
        self.assertEqual(self.staged.read_bytes(), b"encrypted-stage")
        self.assertEqual(self.sidecar.read_bytes(), b"encrypted-metadata")

    def test_unqueued_upload_artifacts_are_removed_after_error(self):
        cleaned = cleanup_unqueued_upload(self.staged, self.sidecar, queued=False)
        self.assertTrue(cleaned)
        self.assertFalse(self.staged.exists())
        self.assertFalse(self.sidecar.exists())

    def test_cleanup_is_idempotent_for_missing_artifacts(self):
        self.staged.unlink()
        cleaned = cleanup_unqueued_upload(self.staged, self.sidecar, queued=False)
        self.assertTrue(cleaned)
        self.assertFalse(self.staged.exists())
        self.assertFalse(self.sidecar.exists())


if __name__ == "__main__":
    unittest.main()
