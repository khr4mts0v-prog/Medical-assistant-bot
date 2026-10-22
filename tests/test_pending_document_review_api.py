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




    def test_duplicate_assignment_is_idempotent_and_does_not_write_files(self):
        pending = {
            "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
            "text": "synthetic OCR", "digest": "a" * 64, "analysis": {},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp.db, "document_exists", return_value=True),
            patch.object(webapp, "_local_archive_original_available", return_value=True),
            patch.object(webapp.db, "delete_pending_doc", return_value=True) as delete_pending,
            patch.object(webapp, "save_local_file") as save_file,
            patch.object(webapp.db, "add_doc") as add_doc,
        ):
            response = webapp.assign_pending_document(
                1, 12, "Саша", "не определено", "Скан", "", uid=123
            )
        self.assertEqual(response.status_code, 303)
        delete_pending.assert_called_once_with(1, 12)
        save_file.assert_not_called()
        add_doc.assert_not_called()

    def test_duplicate_assignment_preserves_pending_copy_if_indexed_original_is_missing(self):
        pending = {
            "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
            "text": "synthetic OCR", "digest": "a" * 64, "analysis": {},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp.db, "document_exists", return_value=True),
            patch.object(webapp, "_local_archive_original_available", return_value=False),
            patch.object(webapp, "_restore_local_indexed_document", return_value=False),
            patch.object(webapp.db, "delete_pending_doc") as delete_pending,
            patch.object(webapp, "save_local_file") as save_file,
        ):
            with self.assertRaises(webapp.HTTPException) as caught:
                webapp.assign_pending_document(
                    1, 12, "Саша", "не определено", "Скан", "", uid=123
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("во входящих сохранена", caught.exception.detail)
        delete_pending.assert_not_called()
        save_file.assert_not_called()


    def test_batch_upload_restores_missing_indexed_original(self):
        with (
            patch.object(webapp, "family", return_value={"id": 1}),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "birth_date": ""}]),
            patch.object(webapp, "ocr_file", return_value="synthetic OCR"),
            patch.object(webapp, "analyze_document", return_value={
                "primary_type": "не определено", "review_required": True,
                "document_types": [], "confidence": "low",
            }),
            patch.object(webapp, "extract_registered_patient", return_value="Саша"),
            patch.object(webapp, "extract_patient_birth_date", return_value=""),
            patch.object(webapp, "parse_date_from_text", return_value=""),
            patch.object(webapp.db, "document_exists", return_value=True),
            patch.object(webapp, "_local_archive_original_available", return_value=False),
            patch.object(webapp, "_restore_local_indexed_document", return_value=True) as restore,
            patch.object(webapp.db, "add_pending_doc") as add_pending,
        ):
            response = self.client.post(
                "/upload",
                data={"family_id": "1", "ai_consent": "false"},
                files=[("files", ("scan.pdf", b"original pdf bytes", "application/pdf"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("оригинал и OCR восстановлены", response.text)
        restore.assert_called_once()
        add_pending.assert_not_called()

    def test_batch_upload_preserves_copy_when_indexed_original_cannot_be_restored(self):
        with (
            patch.object(webapp, "family", return_value={"id": 1}),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "patient_records", return_value=[{"name": "Саша", "birth_date": ""}]),
            patch.object(webapp, "ocr_file", return_value="synthetic OCR"),
            patch.object(webapp, "analyze_document", return_value={
                "primary_type": "не определено", "review_required": True,
                "document_types": [], "confidence": "low",
            }),
            patch.object(webapp, "extract_registered_patient", return_value="Саша"),
            patch.object(webapp, "extract_patient_birth_date", return_value=""),
            patch.object(webapp, "parse_date_from_text", return_value=""),
            patch.object(webapp.db, "document_exists", return_value=True),
            patch.object(webapp, "_local_archive_original_available", return_value=False),
            patch.object(webapp, "_restore_local_indexed_document", return_value=False),
            patch.object(webapp.db, "add_pending_doc", return_value=77) as add_pending,
        ):
            response = self.client.post(
                "/upload",
                data={"family_id": "1", "ai_consent": "false"},
                files=[("files", ("scan.pdf", b"original pdf bytes", "application/pdf"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("копия сохранена во входящих", response.text)
        add_pending.assert_called_once()
        self.assertEqual(add_pending.call_args.args[:3][0:2], (1, "scan.pdf"))
        self.assertEqual(add_pending.call_args.args[4], "synthetic OCR")

    def test_direct_duplicate_upload_restores_missing_local_original(self):
        with (
            patch.object(webapp, "family"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp, "ocr_file", return_value="synthetic OCR"),
            patch.object(webapp, "analyze_document", return_value={
                "primary_type": "не определено", "review_required": True,
                "document_types": [], "confidence": "low",
            }),
            patch.object(webapp, "extract_keywords", return_value=[]),
            patch.object(webapp, "parse_date_from_text", return_value=""),
            patch.object(webapp, "normalize_extension", return_value="pdf"),
            patch.object(webapp.db, "document_exists", return_value=True),
            patch.object(webapp, "_local_archive_original_available", return_value=False),
            patch.object(webapp, "_restore_local_indexed_document", return_value=True) as restore,
            patch.object(webapp.db, "add_doc") as add_doc,
        ):
            response = self.client.post(
                "/families/1/patients/Саша/upload",
                files={"file": ("scan.pdf", b"original pdf bytes", "application/pdf")},
                data={"ai_consent": "false"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Документ восстановлен", response.text)
        restore.assert_called_once()
        add_doc.assert_not_called()

    def test_pending_duplicate_restores_missing_indexed_original_and_ocr_sidecar(self):
        import hashlib
        import tempfile
        from pathlib import Path
        import local_storage

        payload = b"recovered medical document"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            patient_dir = root / "family_1" / local_storage._component("Саша")
            original = patient_dir / "scan.pdf"
            sidecar = patient_dir / "scan.txt"
            source = root / "pending-copy.pdf"
            source.write_bytes(payload)
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp.db, "get_document_storage_paths", return_value={
                    "remote": str(original), "ocr_remote": str(sidecar)
                }),
            ):
                restored = webapp._restore_local_indexed_document(
                    1, "Саша", digest, source, "восстановленный OCR"
                )
            self.assertTrue(restored)
            self.assertEqual(original.read_bytes(), payload)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "восстановленный OCR")
            self.assertEqual(original.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)

    def test_restore_refuses_to_overwrite_corrupt_existing_original(self):
        import hashlib
        import tempfile
        from pathlib import Path
        import local_storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            patient_dir = root / "family_1" / local_storage._component("Саша")
            patient_dir.mkdir(parents=True)
            original = patient_dir / "scan.pdf"
            original.write_bytes(b"corrupt existing bytes")
            sidecar = patient_dir / "scan.txt"
            source = root / "pending-copy.pdf"
            source.write_bytes(b"valid original bytes")
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp.db, "get_document_storage_paths", return_value={
                    "remote": str(original), "ocr_remote": str(sidecar)
                }),
            ):
                restored = webapp._restore_local_indexed_document(
                    1, "Саша", hashlib.sha256(b"valid original bytes").hexdigest(),
                    source, "valid OCR"
                )
            self.assertFalse(restored)
            self.assertEqual(original.read_bytes(), b"corrupt existing bytes")
            self.assertFalse(sidecar.exists())

    def test_local_archive_original_verification_checks_root_and_digest(self):
        import hashlib
        import tempfile
        from pathlib import Path
        import local_storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            patient_dir = root / "family_1" / local_storage._component("Саша")
            patient_dir.mkdir(parents=True)
            original = patient_dir / "original.pdf"
            original.write_bytes(b"known original bytes")
            digest = hashlib.sha256(b"known original bytes").hexdigest()
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp.db, "get_document_storage_paths", return_value={"remote": str(original)}),
            ):
                self.assertTrue(webapp._local_archive_original_available(1, "Саша", digest))
                self.assertFalse(webapp._local_archive_original_available(1, "Саша", "0" * 64))
                outside = root.parent / "outside-medical-archive-test.pdf"
                outside.write_bytes(b"known original bytes")
                try:
                    with patch.object(webapp.db, "get_document_storage_paths", return_value={"remote": str(outside)}):
                        self.assertFalse(webapp._local_archive_original_available(1, "Саша", digest))
                    wrong_patient = root / "family_1" / local_storage._component("Маша") / "original.pdf"
                    wrong_patient.parent.mkdir(parents=True)
                    wrong_patient.write_bytes(b"known original bytes")
                    with patch.object(webapp.db, "get_document_storage_paths", return_value={"remote": str(wrong_patient)}):
                        self.assertFalse(webapp._local_archive_original_available(1, "Саша", digest))
                    symlinked = patient_dir / "symlinked.pdf"
                    symlinked.symlink_to(original)
                    with patch.object(webapp.db, "get_document_storage_paths", return_value={"remote": str(symlinked)}):
                        self.assertFalse(webapp._local_archive_original_available(1, "Саша", digest))
                finally:
                    outside.unlink(missing_ok=True)

    def test_local_file_is_removed_when_ocr_storage_fails(self):
        import tempfile
        from pathlib import Path
        import local_storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            pending = {
                "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
                "text": "synthetic OCR", "digest": "b" * 64, "analysis": {},
            }
            real_save = local_storage.save_file
            calls = {"count": 0}

            def save_then_fail(family_id, patient, filename, source):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("synthetic OCR storage failure")
                return real_save(family_id, patient, filename, source)

            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp, "family"),
                patch.object(webapp, "is_demo_user", return_value=False),
                patch.object(webapp, "STORAGE_BACKEND", "local"),
                patch.object(webapp.db, "get_pending_doc", return_value=pending),
                patch.object(webapp.db, "patients", return_value=["Саша"]),
                patch.object(webapp.db, "document_exists", return_value=False),
                patch.object(webapp, "save_local_file", side_effect=save_then_fail),
                patch.object(webapp.db, "delete_pending_doc") as delete_pending,
                patch.object(webapp.db, "add_doc") as add_doc,
                patch.object(webapp, "format_filename", return_value="scan.pdf"),
                patch.object(webapp, "normalize_extension", return_value="pdf"),
                patch.object(webapp, "extract_keywords", return_value=[]),
            ):
                with self.assertRaises(OSError):
                    webapp.assign_pending_document(
                        1, 12, "Саша", "не определено", "Скан", "", uid=123
                    )
            patient_dir = root / "family_1" / "Саша"
            self.assertTrue(patient_dir.exists())
            self.assertEqual(list(patient_dir.iterdir()), [])
            delete_pending.assert_not_called()
            add_doc.assert_not_called()


    def test_local_files_are_removed_when_database_rejects_insert(self):
        import tempfile
        from pathlib import Path
        import local_storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            pending = {
                "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
                "text": "synthetic OCR", "digest": "c" * 64, "analysis": {},
            }
            with (
                patch.object(local_storage, "DATA_ROOT", root),
                patch.object(webapp, "family"),
                patch.object(webapp, "is_demo_user", return_value=False),
                patch.object(webapp, "STORAGE_BACKEND", "local"),
                patch.object(webapp.db, "get_pending_doc", return_value=pending),
                patch.object(webapp.db, "patients", return_value=["Саша"]),
                patch.object(webapp.db, "document_exists", return_value=False),
                patch.object(webapp.db, "add_doc", return_value=False),
                patch.object(webapp.db, "delete_pending_doc") as delete_pending,
                patch.object(webapp, "format_filename", return_value="scan.pdf"),
                patch.object(webapp, "normalize_extension", return_value="pdf"),
                patch.object(webapp, "extract_keywords", return_value=[]),
            ):
                with self.assertRaises(webapp.HTTPException) as caught:
                    webapp.assign_pending_document(
                        1, 12, "Саша", "не определено", "Скан", "", uid=123
                    )
            self.assertEqual(caught.exception.status_code, 409)
            patient_dir = root / "family_1" / "Саша"
            self.assertTrue(patient_dir.exists())
            self.assertEqual(list(patient_dir.iterdir()), [])
            delete_pending.assert_not_called()


    def test_local_filename_collision_returns_conflict_and_preserves_pending_document(self):
        pending = {
            "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
            "text": "synthetic OCR", "digest": "d" * 64, "analysis": {},
        }
        with (
            patch.object(webapp, "family"),
            patch.object(webapp, "is_demo_user", return_value=False),
            patch.object(webapp, "STORAGE_BACKEND", "local"),
            patch.object(webapp.db, "get_pending_doc", return_value=pending),
            patch.object(webapp.db, "patients", return_value=["Саша"]),
            patch.object(webapp.db, "document_exists", return_value=False),
            patch.object(webapp, "save_local_file", side_effect=FileExistsError("already exists")),
            patch.object(webapp.db, "delete_pending_doc") as delete_pending,
            patch.object(webapp.db, "add_doc") as add_doc,
            patch.object(webapp, "format_filename", return_value="scan.pdf"),
            patch.object(webapp, "normalize_extension", return_value="pdf"),
        ):
            with self.assertRaises(webapp.HTTPException) as caught:
                webapp.assign_pending_document(
                    1, 12, "Саша", "не определено", "Скан", "", uid=123
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("во входящих сохранена", caught.exception.detail)
        delete_pending.assert_not_called()
        add_doc.assert_not_called()



    def test_successful_local_assignment_warns_if_pending_cleanup_fails(self):
        from pathlib import Path

        pending = {
            "id": 12, "name": "scan.pdf", "file_bytes": b"synthetic bytes",
            "text": "synthetic OCR", "digest": "e" * 64, "analysis": {},
        }
        for delete_result in (False, OSError("synthetic SQLite cleanup failure")):
            with self.subTest(delete_result=delete_result):
                delete_patch = patch.object(
                    webapp.db, "delete_pending_doc",
                    side_effect=delete_result if isinstance(delete_result, Exception) else None,
                    return_value=delete_result if not isinstance(delete_result, Exception) else None,
                )
                with (
                    patch.object(webapp, "family"),
                    patch.object(webapp, "is_demo_user", return_value=False),
                    patch.object(webapp, "STORAGE_BACKEND", "local"),
                    patch.object(webapp.db, "get_pending_doc", return_value=pending),
                    patch.object(webapp.db, "patients", return_value=["Саша"]),
                    patch.object(webapp.db, "document_exists", return_value=False),
                    patch.object(webapp, "save_local_file", side_effect=[
                        Path("/tmp/synthetic-original.pdf"), Path("/tmp/synthetic-ocr.txt")
                    ]),
                    delete_patch as delete_pending,
                    patch.object(webapp.db, "add_doc", return_value=True),
                    patch.object(webapp, "format_filename", return_value="scan.pdf"),
                    patch.object(webapp, "normalize_extension", return_value="pdf"),
                    patch.object(webapp, "extract_keywords", return_value=[]),
                ):
                    response = webapp.assign_pending_document(
                        1, 12, "Саша", "не определено", "Скан", "", uid=123
                    )
                self.assertEqual(response.status_code, 303)
                self.assertIn("pending_cleanup_warning=1", response.headers["location"])
                delete_pending.assert_called_once_with(1, 12)



if __name__ == "__main__":
    unittest.main()
