import os
import unittest
from unittest.mock import patch

os.environ.setdefault("WEB_USERNAME", "test-admin")
os.environ.setdefault("WEB_PASSWORD", "test-password-for-unit-tests")
os.environ.setdefault("WEB_SESSION_SECRET", "unit-test-session-secret-with-more-than-32-chars")
os.environ.setdefault("DEMO_USERNAME", "test")
os.environ.setdefault("DEMO_PASSWORD", "test")

import webapp


class PendingDocumentReviewApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(webapp.app, base_url="https://archive.example")
        self.original_overrides = dict(webapp.app.dependency_overrides)
        webapp.app.dependency_overrides[webapp.current_user] = lambda: 123

    def tearDown(self):
        webapp.app.dependency_overrides.clear()
        webapp.app.dependency_overrides.update(self.original_overrides)

    def test_review_api_returns_editor_metadata_without_file_bytes(self):
        pending = {
            "id": 12, "name": "scan.pdf", "created": "2026-10-20", "text": "private OCR",
            "file_bytes": b"secret file bytes", "analysis": {"primary_type": "заключение УЗИ", "display_title": "УЗИ брюшной полости", "suggested_patient_name": "Иванова Мария Сергеевна"},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "birth_date": "10-03-2019"}]),
            patch.object(webapp, "_pdf_page_count", return_value=2),
        ):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient_options"], [{"name": "Саша", "birth_date": "10-03-2019"}])
        self.assertEqual(payload["kind"], "заключение УЗИ")
        self.assertEqual(payload["title"], "УЗИ брюшной полости")
        self.assertEqual(payload["suggested_patient_name"], "Иванова Мария Сергеевна")
        self.assertEqual(payload["page_count"], 2)
        self.assertEqual(payload["preview_kind"], "pdf")
        self.assertNotIn("file_bytes", response.text)
        self.assertNotIn("secret file bytes", response.text)

    def test_review_api_enforces_family_access(self):
        with patch.object(webapp, "family", side_effect=webapp.HTTPException(403, "Нет доступа")):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 403)

    def test_review_api_returns_404_for_missing_document(self):
        with patch.object(webapp, "family"), patch.object(webapp.db, "get_pending_doc", return_value=None):
            response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 404)

    def test_review_api_requires_authentication(self):
        self.client.cookies.clear()
        webapp.app.dependency_overrides.clear()
        response = self.client.get("/api/families/1/inbox/12")
        self.assertEqual(response.status_code, 401)

    def test_create_patient_from_pending_requires_explicit_confirmation(self):
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value={
                "id": 12, "name": "discharge.pdf", "text": "Пациент: Иванова Мария Сергеевна",
                "analysis": {"suggested_patient_name": "Иванова Мария Сергеевна"},
            }),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.db, "patients", return_value=[]),
            patch.object(webapp.db, "add_patient") as add_patient,
        ):
            response = self.client.post(
                "/families/1/inbox/12/create-patient",
                data={"confirm": "no"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 400)
        add_patient.assert_not_called()

    def test_confirmed_patient_creation_files_pending_document(self):
        from fastapi.responses import RedirectResponse
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value={
                "id": 12, "name": "discharge.pdf", "text": "Дата заключения: 12.05.2026",
                "analysis": {"suggested_patient_name": "Иванова Мария Сергеевна",
                             "primary_type": "выписной эпикриз", "display_title": "Выписка"},
            }),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.db, "patients", return_value=[]),
            patch.object(webapp.db, "add_patient") as add_patient,
            patch.object(webapp, "extract_document_date", return_value="12-05-2026"),
            patch.object(webapp, "assign_pending_document", return_value=RedirectResponse(
                "/families/1/patients/Иванова Мария Сергеевна", status_code=303
            )) as assign,
        ):
            response = self.client.post(
                "/families/1/inbox/12/create-patient",
                data={"confirm": "yes"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        add_patient.assert_called_once_with(1, "Иванова Мария Сергеевна")
        assign.assert_called_once_with(
            1, 12, "Иванова Мария Сергеевна", "выписной эпикриз", "Выписка", "12-05-2026", 123
        )


    def test_retry_reuses_existing_patient_if_previous_assignment_failed(self):
        from fastapi.responses import RedirectResponse
        patient = "Иванова Мария Сергеевна"
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value={
                "id": 12, "name": "discharge.pdf", "text": "Дата заключения: 12.05.2026",
                "analysis": {"suggested_patient_name": patient,
                             "primary_type": "выписной эпикриз", "display_title": "Выписка"},
            }),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.db, "patients", return_value=[patient]),
            patch.object(webapp.db, "add_patient") as add_patient,
            patch.object(webapp, "extract_document_date", return_value="12-05-2026"),
            patch.object(webapp, "assign_pending_document", return_value=RedirectResponse(
                "/families/1/patients/Иванова Мария Сергеевна", status_code=303
            )) as assign,
        ):
            response = self.client.post(
                "/families/1/inbox/12/create-patient",
                data={"confirm": "yes"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        add_patient.assert_not_called()
        assign.assert_called_once_with(
            1, 12, patient, "выписной эпикриз", "Выписка", "12-05-2026", 123
        )


    def test_retry_uses_existing_patient_canonical_spelling(self):
        from fastapi.responses import RedirectResponse
        canonical = "Иванова Мария Сергеевна"
        candidate = "ИВАНОВА МАРИЯ СЕРГЕЕВНА"
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value={
                "id": 12, "name": "discharge.pdf", "text": "Дата заключения: 12.05.2026",
                "analysis": {"suggested_patient_name": candidate,
                             "primary_type": "выписной эпикриз", "display_title": "Выписка"},
            }),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp.db, "patients", return_value=[canonical]),
            patch.object(webapp.db, "add_patient") as add_patient,
            patch.object(webapp, "extract_document_date", return_value="12-05-2026"),
            patch.object(webapp, "assign_pending_document", return_value=RedirectResponse(
                "/families/1/patients/Иванова Мария Сергеевна", status_code=303
            )) as assign,
        ):
            response = self.client.post(
                "/families/1/inbox/12/create-patient",
                data={"confirm": "yes"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        add_patient.assert_not_called()
        assign.assert_called_once_with(
            1, 12, canonical, "выписной эпикриз", "Выписка", "12-05-2026", 123
        )


    def test_demo_retry_reuses_existing_patient_at_card_limit(self):
        from fastapi.responses import RedirectResponse
        patient = "Иванова Мария Сергеевна"
        with (
            patch.object(webapp, "family"),
            patch.object(webapp.db, "get_pending_doc", return_value={
                "id": 12, "name": "discharge.pdf", "text": "Дата заключения: 12.05.2026",
                "analysis": {"suggested_patient_name": patient,
                             "primary_type": "выписной эпикриз", "display_title": "Выписка"},
            }),
            patch.object(webapp, "is_demo_user", return_value=True),
            patch.object(webapp.tenancy, "refresh_demo_expiry"),
            patch.object(webapp, "DEMO_MAX_PATIENTS", 1),
            patch.object(webapp.db, "patients", return_value=[patient]),
            patch.object(webapp.db, "add_patient") as add_patient,
            patch.object(webapp, "extract_document_date", return_value="12-05-2026"),
            patch.object(webapp, "assign_pending_document", return_value=RedirectResponse(
                "/families/1/patients/Иванова Мария Сергеевна", status_code=303
            )) as assign,
        ):
            response = self.client.post(
                "/families/1/inbox/12/create-patient",
                data={"confirm": "yes"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        add_patient.assert_not_called()
        assign.assert_called_once_with(
            1, 12, patient, "выписной эпикриз", "Выписка", "12-05-2026", 123
        )


    def test_yandex_files_are_rolled_back_when_index_write_fails(self):
        class FakeDisk:
            def __init__(self):
                self.uploaded = []
                self.deleted = []
            def ensure_folder(self, path):
                pass
            def upload_file(self, local, remote):
                self.uploaded.append(remote)
            def delete_file(self, remote):
                self.deleted.append(remote)
                return True

        disk = FakeDisk()
        pending = {
            "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic pdf bytes",
            "text": "synthetic OCR text", "digest": "a" * 64, "analysis": {},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "yandex"),
            patch.object(webapp.tenancy, "get_yadisk_token", return_value="synthetic-token"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp.db, "document_exists", return_value=False),
            patch.object(webapp, "YaDiskClient", return_value=disk),
            patch.object(webapp, "format_filename", return_value="scan.pdf"),
            patch.object(webapp, "normalize_extension", return_value="pdf"),
            patch.object(webapp, "extract_keywords", return_value=[]),
            patch.object(webapp.db, "add_doc", return_value=False),
            patch.object(webapp.db, "delete_pending_doc") as delete_pending,
        ):
            with self.assertRaises(webapp.HTTPException) as caught:
                webapp.assign_pending_document(
                    1, 12, "Саша", "не определено", "Скан", "", uid=123
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(disk.uploaded), 2)
        self.assertEqual(disk.deleted, disk.uploaded)
        delete_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
