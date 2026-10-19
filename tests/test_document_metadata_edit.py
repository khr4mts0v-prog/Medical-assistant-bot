import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DocumentMetadataEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db=os.environ.get("DB_PATH")
        self.old_key=os.environ.get("FERNET_KEY")
        os.environ["DB_PATH"]=str(Path(self.tmp.name)/"test.sqlite3")
        from cryptography.fernet import Fernet
        os.environ["FERNET_KEY"]=Fernet.generate_key().decode()
        import tenancy
        from unittest.mock import patch
        self.db_path_patch=patch.object(tenancy, 'DB_PATH', Path(os.environ['DB_PATH']))
        self.key_patch=patch.object(tenancy, 'FERNET_KEY', os.environ['FERNET_KEY'])
        self.db_path_patch.start()
        self.key_patch.start()
        import database as db
        self.db=db
        tenancy.init()
        db.init()
        self.fid=tenancy.create_family("Тестовый архив",1)
        self.db.add_patient(self.fid,"Тестовый пациент")
        self.db.add_doc(self.fid,"Тестовый пациент","scan.jpg","не определено","10-03-2019",
                   "/tmp/original.jpg","/tmp/ocr.txt","OCR text",[],"digest-test",
                   analysis={"primary_type":"не определено","review_required":True})
        self.doc_id=self.db.search(self.fid,"Тестовый пациент")[0]["id"]

    def tearDown(self):
        if self.old_db is None: os.environ.pop("DB_PATH",None)
        else: os.environ["DB_PATH"]=self.old_db
        if self.old_key is None: os.environ.pop("FERNET_KEY",None)
        else: os.environ["FERNET_KEY"]=self.old_key
        self.db_path_patch.stop()
        self.key_patch.stop()
        self.tmp.cleanup()

    def test_update_doc_metadata_preserves_original_and_ocr(self):
        analysis={"primary_type":"заключение УЗИ","document_types":["заключение УЗИ"],
                  "types":["заключение УЗИ"],"confidence":"manual","review_required":False,
                  "display_title":"УЗИ почек и мочевого пузыря"}
        self.assertTrue(self.db.update_doc_metadata(self.fid,self.doc_id,"заключение УЗИ","17-03-2025",analysis))
        doc=self.db.get_doc(self.fid,self.doc_id)
        self.assertEqual(doc["kind"],"заключение УЗИ")
        self.assertEqual(doc["date"],"17-03-2025")
        self.assertEqual(doc["analysis"]["display_title"],"УЗИ почек и мочевого пузыря")
        self.assertEqual(doc["text"],"OCR text")
        self.assertEqual(doc["remote"],"/tmp/original.jpg")
        self.assertEqual(doc["ocr_remote"],"/tmp/ocr.txt")

    def test_manual_ocr_edit_is_encrypted_and_used_for_search(self):
        corrected = "Заключение УЗИ: умеренное расширение лоханки"
        self.assertTrue(self.db.update_doc_text(self.fid, self.doc_id, corrected))
        doc = self.db.get_doc(self.fid, self.doc_id)
        self.assertEqual(doc["text"], corrected)
        self.assertEqual(doc["remote"], "/tmp/original.jpg")
        self.assertEqual(doc["ocr_remote"], "/tmp/ocr.txt")
        self.assertTrue(self.db.search(self.fid, "Тестовый пациент", "расширение"))
        with self.db.connect() as connection:
            raw = connection.execute("SELECT text FROM docs WHERE family_id=? AND id=?", (self.fid, self.doc_id)).fetchone()["text"]
        self.assertNotIn(corrected.encode("utf-8"), raw)

    def test_update_is_scoped_to_family_and_document(self):
        self.assertFalse(self.db.update_doc_metadata(self.fid+999,self.doc_id,"заключение УЗИ","17-03-2025",{}))
        self.assertFalse(self.db.update_doc_metadata(self.fid,self.doc_id+999,"заключение УЗИ","17-03-2025",{}))

if __name__ == "__main__":
    unittest.main()