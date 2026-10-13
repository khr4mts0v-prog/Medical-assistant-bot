import contextlib
import io
import sys
import unittest
from unittest import mock

from scripts import probe_public_datasets as probe


class PublicDatasetProbeTests(unittest.TestCase):
    def test_retry_policy_covers_gateway_timeout(self):
        retry = probe.SESSION.get_adapter("https://").max_retries
        self.assertGreaterEqual(retry.total, 3)
        self.assertIn(504, retry.status_forcelist)
        self.assertIn(429, retry.status_forcelist)

    def test_network_timeouts_are_bounded(self):
        self.assertGreater(probe.CONNECT_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(probe.CONNECT_TIMEOUT_SECONDS, 15)
        self.assertGreater(probe.READ_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(probe.READ_TIMEOUT_SECONDS, 60)

    def test_any_selected_source_failure_returns_nonzero(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["probe_public_datasets.py", "--dataset", "all"]), \
             mock.patch.object(probe, "probe_rumedprime", side_effect=RuntimeError("source unavailable")), \
             mock.patch.object(probe, "probe_ruclinner", return_value=True), \
             contextlib.redirect_stdout(output):
            result = probe.main()

        self.assertEqual(result, 1)
        self.assertIn("RuMedPrimeData", output.getvalue())
        self.assertIn("DIAGNOSTIC FAILED", output.getvalue())

    def test_all_selected_sources_success_returns_zero(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["probe_public_datasets.py", "--dataset", "all"]), \
             mock.patch.object(probe, "probe_rumedprime"), \
             mock.patch.object(probe, "probe_ruclinner", return_value=True), \
             contextlib.redirect_stdout(output):
            result = probe.main()

        self.assertEqual(result, 0)
        self.assertIn("DIAGNOSTIC COMPLETE", output.getvalue())
        self.assertIn("BEGIN source=RuMedPrimeData", output.getvalue())
        self.assertIn("BEGIN source=RuClinNER", output.getvalue())


if __name__ == "__main__":
    unittest.main()
