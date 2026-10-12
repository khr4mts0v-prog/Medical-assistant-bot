import os
import unittest
from fastapi.security import HTTPBasicCredentials

os.environ["WEB_USERNAME"] = "test-admin"
os.environ["WEB_PASSWORD"] = "test-password-for-unit-tests"

import webapp

class WebAuthTests(unittest.TestCase):
    def test_valid_credentials_map_to_negative_user_id(self):
        uid = webapp.current_user(HTTPBasicCredentials(username="test-admin", password="test-password-for-unit-tests"))
        self.assertLess(uid, 0)

    def test_invalid_password_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            webapp.current_user(HTTPBasicCredentials(username="test-admin", password="wrong"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_page_escapes_title(self):
        response = webapp.page("<script>alert(1)</script>", "safe body")
        self.assertNotIn("<title><script>", response.body.decode())
        self.assertIn("&lt;script&gt;", response.body.decode())

if __name__ == "__main__":
    unittest.main()
