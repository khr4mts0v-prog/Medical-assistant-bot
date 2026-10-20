import unittest
from unittest.mock import patch

from starlette.requests import Request

import webapp


class RequestRateLimitTests(unittest.TestCase):
    def setUp(self):
        with webapp.RATE_LIMIT_LOCK:
            webapp.RATE_LIMIT_EVENTS.clear()

    def tearDown(self):
        with webapp.RATE_LIMIT_LOCK:
            webapp.RATE_LIMIT_EVENTS.clear()

    def test_ai_rate_limit_blocks_excess_requests_and_expires(self):
        with patch.dict(webapp.RATE_LIMIT_POLICIES, {"ai": (2, 10.0)}):
            self.assertEqual(webapp._consume_rate_limit("ai", "uid:1", now=0), (False, 0))
            self.assertEqual(webapp._consume_rate_limit("ai", "uid:1", now=1), (False, 0))
            limited, retry_after = webapp._consume_rate_limit("ai", "uid:1", now=2)
            self.assertTrue(limited)
            self.assertGreaterEqual(retry_after, 1)
            self.assertEqual(webapp._consume_rate_limit("ai", "uid:1", now=11.1), (False, 0))

    def test_limits_are_separated_by_identity_and_operation(self):
        with patch.dict(webapp.RATE_LIMIT_POLICIES, {"ai": (1, 60.0), "upload": (1, 60.0)}):
            self.assertEqual(webapp._consume_rate_limit("ai", "uid:1", now=1), (False, 0))
            self.assertEqual(webapp._consume_rate_limit("ai", "uid:2", now=1), (False, 0))
            self.assertEqual(webapp._consume_rate_limit("upload", "uid:1", now=1), (False, 0))
            self.assertTrue(webapp._consume_rate_limit("ai", "uid:1", now=2)[0])

    def test_only_expensive_post_routes_are_limited(self):
        self.assertEqual(webapp._rate_limit_category("/api/intelligent-search", "POST"), "ai")
        self.assertEqual(webapp._rate_limit_category("/upload", "POST"), "upload")
        self.assertEqual(webapp._rate_limit_category("/families/1/patients/Sasha/upload", "POST"), "upload")
        self.assertIsNone(webapp._rate_limit_category("/api/intelligent-search", "GET"))
        self.assertIsNone(webapp._rate_limit_category("/api/home", "POST"))

    def test_demo_cookie_identity_is_hashed_not_logged_as_raw_value(self):
        request = Request({
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/api/intelligent-search",
            "raw_path": b"/api/intelligent-search",
            "query_string": b"",
            "headers": [(b"cookie", b"medical_demo_session=secret-cookie-value")],
            "client": ("127.0.0.1", 12345),
            "server": ("archive.example", 443),
        })
        identity = webapp._rate_limit_identity(request)
        self.assertTrue(identity.startswith("demo:"))
        self.assertNotIn("secret-cookie-value", identity)


if __name__ == "__main__":
    unittest.main()
