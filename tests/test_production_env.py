import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

import scripts.check_production_env as preflight


class ProductionEnvironmentPreflightTests(unittest.TestCase):
    def valid_env(self):
        return {
            "WEB_USERNAME": "family-owner",
            "WEB_PASSWORD": "a-long-unique-production-password",
            "WEB_SESSION_SECRET": "s" * 48,
            "FERNET_KEY": Fernet.generate_key().decode("ascii"),
            "DEMO_USERNAME": "",
            "DEMO_PASSWORD": "",
            "DOCUMENT_STORAGE_BACKEND": "local",
            "LOCAL_STORAGE_AT_REST_PROTECTED": "true",
        }

    def test_accepts_explicitly_secured_private_configuration(self):
        self.assertEqual(preflight.validate(self.valid_env()), [])

    def test_rejects_plaintext_local_storage_without_explicit_protection(self):
        env = self.valid_env()
        env["LOCAL_STORAGE_AT_REST_PROTECTED"] = "false"
        errors = preflight.validate(env)
        self.assertTrue(any("plaintext files" in error for error in errors))

    def test_rejects_default_demo_credentials_and_short_password(self):
        env = self.valid_env()
        env["DEMO_USERNAME"] = "test"
        env["DEMO_PASSWORD"] = "test"
        env["WEB_PASSWORD"] = "short"
        errors = preflight.validate(env)
        self.assertTrue(any("Default demo credentials" in error for error in errors))
        self.assertTrue(any("WEB_PASSWORD" in error for error in errors))

    def test_rejects_invalid_fernet_key_and_implicit_demo_defaults(self):
        env = self.valid_env()
        env["FERNET_KEY"] = "not-a-fernet-key"
        del env["DEMO_USERNAME"]
        del env["DEMO_PASSWORD"]
        errors = preflight.validate(env)
        self.assertTrue(any("FERNET_KEY" in error for error in errors))
        self.assertTrue(any("DEMO_USERNAME" in error for error in errors))

    def test_env_parser_and_permissions_check_do_not_print_secret_values(self):
        env = self.valid_env()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("\n".join(f"{key}={value}" for key, value in env.items()), encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(preflight.parse_env(path), env)
            with patch("sys.argv", ["check_production_env.py", "--env-file", str(path)]):
                self.assertEqual(preflight.main(), 0)
            path.chmod(0o644)
            with patch("sys.argv", ["check_production_env.py", "--env-file", str(path)]):
                self.assertEqual(preflight.main(), 2)


if __name__ == "__main__":
    unittest.main()
