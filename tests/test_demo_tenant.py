import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import database as db
import local_storage
import tenancy

class DemoTenantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = tenancy.DB_PATH
        self.old_key = tenancy.FERNET_KEY
        self.old_storage = local_storage.DATA_ROOT
        tenancy.DB_PATH = Path(self.temp.name) / "demo.sqlite3"
        tenancy.FERNET_KEY = Fernet.generate_key().decode()
        local_storage.DATA_ROOT = Path(self.temp.name) / "documents"
        db.init()

    def tearDown(self):
        tenancy.DB_PATH = self.old_db
        tenancy.FERNET_KEY = self.old_key
        local_storage.DATA_ROOT = self.old_storage
        self.temp.cleanup()

    def test_demo_tenant_is_marked_and_can_be_deleted_without_touching_other_family(self):
        demo_uid = -123456789
        demo_fid = tenancy.ensure_demo_family(demo_uid)
        ordinary_fid = tenancy.create_family("Реальный архив", -987654321)
        self.assertTrue(tenancy.is_demo_family(demo_fid))
        self.assertFalse(tenancy.is_demo_family(ordinary_fid))
        with tenancy.connect() as c:
            c.execute("UPDATE demo_tenants SET expires_at=datetime('now','-1 minute') WHERE family_id=?", (demo_fid,))
        self.assertEqual(tenancy.expired_demo_families(), [demo_fid])
        self.assertTrue(tenancy.delete_demo_family(demo_fid))
        self.assertFalse(tenancy.delete_demo_family(ordinary_fid))
        self.assertEqual([x["id"] for x in tenancy.families_for_user(-987654321)], [ordinary_fid])

    def test_quota_counter_includes_indexed_and_pending_documents(self):
        fid = tenancy.create_family("Quota", -111222333)
        db.add_patient(fid, "Patient A")
        self.assertEqual(db.family_document_count(fid), 0)
        self.assertIsNotNone(db.add_pending_doc(fid, "pending.pdf", "pending-digest", b"pdf", "OCR text", {}))
        self.assertEqual(db.family_document_count(fid), 1)
        self.assertTrue(db.add_doc(fid, "Patient A", "lab.pdf", "лабораторный отчёт", "01-01-2025",
                                  "/tmp/lab.pdf", "/tmp/lab.txt", "Гемоглобин 120 г/л", ["гемоглобин"],
                                  "stored-digest", analysis={"primary_type": "лабораторный отчёт"}))
        self.assertEqual(db.family_document_count(fid), 2)


    def test_http_upload_ai_consent_and_expired_file_cleanup(self):
        import webapp
        client = TestClient(webapp.app, base_url="https://archive.example")
        with patch.object(webapp, "DEMO_USERNAME", "test"), \
             patch.object(webapp, "DEMO_PASSWORD", "test"), \
             patch.object(webapp, "ocr_file", return_value="Лабораторный анализ крови. Гемоглобин 120 г/л"), \
             patch.object(webapp, "analyze_document", return_value={
                 "primary_type": "лабораторный отчёт", "document_types": ["лабораторный отчёт"],
                 "types": ["лабораторный отчёт"], "confidence": "high", "review_required": True,
                 "lab_results": [], "diagnoses": [], "medications": [], "dates": []}), \
             patch.object(webapp, "extract_registered_patient", return_value="Test Patient"), \
             patch.object(webapp, "extract_patient_birth_date", return_value=None), \
             patch.object(webapp, "extract_keywords", return_value=["гемоглобин"]), \
             patch.object(webapp, "classify_with_ai", side_effect=lambda text, analysis: dict(analysis)) as classifier:
            client.get("/", auth=("test", "test"))
            cookie = client.cookies.get("medical_demo_session")
            demo_uid = -(webapp.DEMO_UID_FLOOR + int(hashlib.sha256(cookie.encode()).hexdigest()[:14], 16))
            fid = tenancy.families_for_user(demo_uid)[0]["id"]
            client.post(f"/families/{fid}/patients", data={"name": "Test Patient"}, auth=("test", "test"))
            first = client.post("/upload", data={"family_id": str(fid), "ai_consent": "false"},
                                files=[("files", ("first.pdf", b"first document", "application/pdf"))], auth=("test", "test"))
            self.assertEqual(first.status_code, 200)
            classifier.assert_not_called()
            second = client.post("/upload", data={"family_id": str(fid), "ai_consent": "true"},
                                 files=[("files", ("second.pdf", b"second document", "application/pdf"))], auth=("test", "test"))
            self.assertEqual(second.status_code, 200)
            classifier.assert_called_once()
            self.assertEqual(db.family_document_count(fid), 2)

        demo_dir = local_storage.DATA_ROOT / f"family_{fid}"
        self.assertTrue(demo_dir.exists())
        private_uid = -(int(hashlib.sha256(webapp.WEB_USERNAME.encode()).hexdigest()[:12], 16) or 1)
        private_fid = tenancy.create_family("Private archive", private_uid)
        private_dir = local_storage.DATA_ROOT / f"family_{private_fid}" / "Keep"
        private_dir.mkdir(parents=True)
        private_file = private_dir / "keep.txt"
        private_file.write_text("preserve", encoding="utf-8")
        with tenancy.connect() as conn:
            conn.execute("UPDATE demo_tenants SET expires_at=datetime('now','-1 minute') WHERE family_id=?", (fid,))
        self.assertEqual(webapp._cleanup_expired_demo_tenants_once(), 1)
        self.assertFalse(demo_dir.exists())
        self.assertFalse(tenancy.is_demo_family(fid))
        self.assertTrue(private_file.exists())
        self.assertIsNotNone(tenancy.get_family(private_fid))

    def test_demo_active_tenant_limit_is_enforced(self):
        tenancy.ensure_demo_family(-123123, max_active=1)
        with self.assertRaises(RuntimeError):
            tenancy.ensure_demo_family(-456456, max_active=1)

if __name__ == "__main__":
    unittest.main()