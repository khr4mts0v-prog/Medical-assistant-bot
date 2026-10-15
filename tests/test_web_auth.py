import os
import unittest
from fastapi.security import HTTPBasicCredentials

os.environ["WEB_USERNAME"] = "test-admin"
os.environ["WEB_PASSWORD"] = "test-password-for-unit-tests"
os.environ["WEB_SESSION_SECRET"] = "unit-test-session-secret-with-more-than-32-chars"
# Demo credentials default to test/test for the current MVP test phase.
os.environ["DEMO_USERNAME"] = "test"
os.environ["DEMO_PASSWORD"] = "test"

import webapp

class WebAuthTests(unittest.TestCase):
    def test_valid_credentials_map_to_negative_user_id(self):
        uid = webapp.current_user(None, HTTPBasicCredentials(username="test-admin", password="test-password-for-unit-tests"))
        self.assertLess(uid, 0)

    def test_invalid_password_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            webapp.current_user(None, HTTPBasicCredentials(username="test-admin", password="wrong"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_demo_login_can_be_disabled_with_empty_configuration(self):
        from unittest.mock import patch
        with patch.object(webapp, "DEMO_USERNAME", ""), patch.object(webapp, "DEMO_PASSWORD", ""):
            with self.assertRaises(Exception) as ctx:
                webapp.current_user(None, HTTPBasicCredentials(username="test", password="test"))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_demo_credentials_are_a_separate_identity(self):
        from unittest.mock import patch
        with patch.object(webapp, "DEMO_USERNAME", "test"), patch.object(webapp, "DEMO_PASSWORD", "test"), \
             patch.object(webapp.tenancy, "ensure_demo_family") as ensure:
            demo_uid = webapp.current_user(None, HTTPBasicCredentials(username="test", password="test"))
        self.assertEqual(demo_uid, webapp.DEMO_UID)
        self.assertNotEqual(demo_uid, -(int(__import__("hashlib").sha256(b"test-admin").hexdigest()[:12], 16) or 1))
        ensure.assert_called_once_with(webapp.DEMO_UID, max_active=webapp.DEMO_MAX_ACTIVE_TENANTS)


    def test_demo_session_cookie_ids_are_isolated(self):
        from starlette.requests import Request
        from unittest.mock import patch
        def request(cookie=""):
            headers = [(b"host", b"archive.example"), (b"x-forwarded-proto", b"https")]
            if cookie:
                headers.append((b"cookie", ("medical_demo_session=" + cookie).encode()))
            return Request({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1",
                "method":"GET","scheme":"https","path":"/","raw_path":b"/","query_string":b"",
                "headers":headers,"client":("203.0.113.4",1234),"server":("archive.example",443)})
        with patch.object(webapp, "DEMO_USERNAME", "test"), patch.object(webapp, "DEMO_PASSWORD", "test"), \
             patch.object(webapp.tenancy, "ensure_demo_family"):
            uid_a = webapp.current_user(request("browser-a-session"), HTTPBasicCredentials(username="test",password="test"))
            uid_b = webapp.current_user(request("browser-b-session"), HTTPBasicCredentials(username="test",password="test"))
            self.assertNotEqual(uid_a, uid_b)
            uid_a2 = webapp.current_user(request("browser-a-session"), HTTPBasicCredentials(username="test",password="test"))
            self.assertEqual(uid_a2, -(webapp.DEMO_UID_FLOOR + int(__import__("hashlib").sha256(b"browser-a-session").hexdigest()[:14],16)))


    def test_http_middleware_sets_secure_per_browser_cookie(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        with patch.object(webapp, "DEMO_USERNAME", "test"), patch.object(webapp, "DEMO_PASSWORD", "test"), \
             patch.object(webapp.tenancy, "ensure_demo_family"), patch.object(webapp.tenancy, "families_for_user", return_value=[]):
            client_a = TestClient(webapp.app, base_url="https://archive.example")
            client_b = TestClient(webapp.app, base_url="https://archive.example")
            first = client_a.get("/", auth=("test", "test"))
            second = client_b.get("/", auth=("test", "test"))
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            cookie_a = client_a.cookies.get("medical_demo_session")
            cookie_b = client_b.cookies.get("medical_demo_session")
            self.assertTrue(cookie_a)
            self.assertTrue(cookie_b)
            self.assertNotEqual(cookie_a, cookie_b)
            cookie_header = first.headers.get("set-cookie", "")
            self.assertIn("HttpOnly", cookie_header)
            self.assertIn("Secure", cookie_header)
            self.assertIn("SameSite=lax", cookie_header)
            repeat = client_a.get("/", auth=("test", "test"))
            self.assertEqual(client_a.cookies.get("medical_demo_session"), cookie_a)
            self.assertIn("Max-Age=7200", repeat.headers.get("set-cookie", ""))

    def test_demo_upload_quota_counts_existing_documents(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        with patch.object(webapp.db, "family_document_count", return_value=webapp.DEMO_MAX_DOCUMENTS):
            with self.assertRaises(HTTPException) as ctx:
                webapp.enforce_demo_document_quota(123, 1)
            self.assertEqual(ctx.exception.status_code, 413)

    def test_page_escapes_title(self):
        response = webapp.page("<script>alert(1)</script>", "safe body")
        self.assertNotIn("<title><script>", response.body.decode())
        self.assertIn("&lt;script&gt;", response.body.decode())

    def test_login_creates_secure_session_and_restores_authentication(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        with patch.object(webapp.tenancy, "ensure_demo_family"), patch.object(webapp.tenancy, "families_for_user", return_value=[]):
            client = TestClient(webapp.app, base_url="https://archive.example")
            response = client.post("/auth/login", data={"username": "test", "password": "test", "next": "/app"}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers.get("location"), "/app")
            cookie = client.cookies.get(webapp.SESSION_COOKIE_NAME)
            self.assertTrue(cookie)
            cookie_header = response.headers.get("set-cookie", "")
            self.assertIn("HttpOnly", cookie_header)
            self.assertIn("Secure", cookie_header)
            self.assertIn("SameSite=lax", cookie_header)
            status = client.get("/auth/status")
            self.assertEqual(status.status_code, 200)
            self.assertIn('"authenticated":true', status.text)

    def test_missing_or_expired_session_returns_401_without_basic_challenge(self):
        from fastapi.testclient import TestClient
        import time
        from unittest.mock import patch
        with patch.object(webapp.tenancy, "ensure_demo_family"):
            client = TestClient(webapp.app, base_url="https://archive.example")
            response = client.get("/auth/status")
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("WWW-Authenticate", response.headers)
            expired = webapp._make_session(webapp.DEMO_UID, expires_at=int(time.time()) - 1)
            client.cookies.set(webapp.SESSION_COOKIE_NAME, expired, domain="archive.example", path="/")
            expired_response = client.get("/auth/status")
            self.assertEqual(expired_response.status_code, 401)

    def test_logout_clears_session_and_demo_cookies(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        with patch.object(webapp.tenancy, "ensure_demo_family"), patch.object(webapp.tenancy, "families_for_user", return_value=[]):
            client = TestClient(webapp.app, base_url="https://archive.example")
            login = client.post("/auth/login", data={"username": "test", "password": "test"}, follow_redirects=False)
            self.assertEqual(login.status_code, 303)
            self.assertTrue(client.cookies.get(webapp.SESSION_COOKIE_NAME))
            logout = client.post("/auth/logout", follow_redirects=False)
            self.assertEqual(logout.status_code, 303)
            self.assertEqual(logout.headers.get("location"), "/login")
            self.assertFalse(client.cookies.get(webapp.SESSION_COOKIE_NAME))
            status = client.get("/auth/status")
            self.assertEqual(status.status_code, 401)

    def test_login_rejects_invalid_credentials(self):
        from fastapi.testclient import TestClient
        client = TestClient(webapp.app, base_url="https://archive.example")
        response = client.post("/auth/login", data={"username": "test", "password": "wrong"}, follow_redirects=False)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Неверный логин или пароль", response.text)
        self.assertFalse(client.cookies.get(webapp.SESSION_COOKIE_NAME))

    def test_legacy_basic_auth_remains_supported(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        client = TestClient(webapp.app, base_url="https://archive.example")
        response = client.get("/auth/status", auth=("test-admin", "test-password-for-unit-tests"))
        self.assertEqual(response.status_code, 200)
        self.assertIn('"authenticated":true', response.text)

if __name__ == "__main__":
    unittest.main()