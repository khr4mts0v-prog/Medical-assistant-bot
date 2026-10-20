import unittest
from cryptography.fernet import Fernet

from scripts.check_production_env import validate


class DeploymentPreflightTests(unittest.TestCase):
    def valid_values(self):
        return {
            "WEB_USERNAME": "admin",
            "WEB_PASSWORD": "long-admin-test-password-123456",
            "WEB_SESSION_SECRET": "session-secret-for-tests-that-is-long-enough-123",
            "FERNET_KEY": Fernet.generate_key().decode(),
            "DEMO_USERNAME": "test",
            "DEMO_PASSWORD": "test",
            "DOCUMENT_STORAGE_BACKEND": "local",
        }

    def test_testing_mode_allows_intentional_test_credentials_and_plaintext_files(self):
        self.assertEqual(validate(self.valid_values(), mode="testing"), [])

    def test_production_mode_still_rejects_test_credentials_and_unprotected_local_files(self):
        errors = validate(self.valid_values(), mode="production")
        self.assertTrue(any("Default demo credentials" in error for error in errors))
        self.assertTrue(any("plaintext files" in error for error in errors))

    def test_testing_mode_still_requires_valid_admin_session_and_encryption_configuration(self):
        values = self.valid_values()
        values["WEB_SESSION_SECRET"] = "short"
        values["FERNET_KEY"] = "not-a-fernet-key"
        errors = validate(values, mode="testing")
        self.assertTrue(any("WEB_SESSION_SECRET" in error for error in errors))
        self.assertTrue(any("FERNET_KEY" in error for error in errors))

    def test_demo_credentials_must_be_configured_as_a_pair(self):
        values = self.valid_values()
        values["DEMO_PASSWORD"] = ""
        errors = validate(values, mode="testing")
        self.assertTrue(any("both be empty" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
