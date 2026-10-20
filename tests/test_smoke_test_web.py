import unittest

from scripts.smoke_test_web import demo_login_enabled


class SmokeTestConfigurationTests(unittest.TestCase):
    def test_demo_login_is_disabled_when_both_credentials_are_empty(self):
        self.assertFalse(demo_login_enabled({"DEMO_USERNAME": "", "DEMO_PASSWORD": ""}))

    def test_demo_login_is_enabled_for_configured_credentials(self):
        self.assertTrue(demo_login_enabled({"DEMO_USERNAME": "demo-user", "DEMO_PASSWORD": "long-demo-password"}))

    def test_partial_demo_credentials_do_not_enable_demo_mode(self):
        self.assertFalse(demo_login_enabled({"DEMO_USERNAME": "demo-user", "DEMO_PASSWORD": ""}))
        self.assertFalse(demo_login_enabled({"DEMO_USERNAME": "", "DEMO_PASSWORD": "long-demo-password"}))


if __name__ == "__main__":
    unittest.main()
