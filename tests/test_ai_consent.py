import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_consent
import tenancy


class PersistentAIConsentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "consent.sqlite3"
        self.db_path_patch = patch.object(tenancy, "DB_PATH", self.db_path)
        self.db_path_patch.start()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_new_account_has_no_consent(self):
        self.assertFalse(ai_consent.get(101)["granted"])

    def test_explicit_grant_persists_across_reads(self):
        state = ai_consent.set_consent(101, True)
        self.assertTrue(state["granted"])
        self.assertTrue(state["granted_at"])
        self.assertTrue(ai_consent.get(101)["granted"])

    def test_consent_is_isolated_between_accounts(self):
        ai_consent.set_consent(101, True)
        self.assertFalse(ai_consent.get(202)["granted"])

    def test_revoke_prevents_future_external_ai_processing(self):
        ai_consent.set_consent(101, True)
        state = ai_consent.set_consent(101, False)
        self.assertFalse(state["granted"])
        self.assertIsNone(state["granted_at"])
        self.assertFalse(ai_consent.get(101)["granted"])

    def test_non_boolean_grant_is_rejected(self):
        for invalid in ("true", 1, None, "yes"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    ai_consent.set_consent(101, invalid)


if __name__ == "__main__":
    unittest.main()
