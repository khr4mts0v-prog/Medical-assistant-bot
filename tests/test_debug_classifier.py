import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClassifierDiagnosticCliTests(unittest.TestCase):
    def run_debugger(self, *args, text=""):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "debug_classifier.py"), *args],
            input=text,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def test_default_output_hides_source_text_and_shows_stages(self):
        private_marker = "PRIVATE_TEST_MARKER_12345"
        text = (
            "ЗАКЛЮЧЕНИЕ МРТ\n"
            "Магнитно-резонансная томография головного мозга.\n"
            f"Комментарий: {private_marker}\n"
        )
        result = self.run_debugger(text=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(private_marker, result.stdout)
        self.assertIn("Этап 1", result.stdout)
        self.assertIn("Этап 3", result.stdout)
        self.assertIn("Этап 4", result.stdout)

    def test_json_output_hides_source_text_by_default(self):
        private_marker = "PRIVATE_TEST_MARKER_JSON_12345"
        result = self.run_debugger("--json", text=f"Текст: {private_marker}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(private_marker, result.stdout)
        self.assertIn('"raw_rule_scores"', result.stdout)
        self.assertIn('"prefix_changes"', result.stdout)


if __name__ == "__main__":
    unittest.main()
