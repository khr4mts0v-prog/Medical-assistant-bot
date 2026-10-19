import json
import os
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

_TMP = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = str(Path(_TMP.name) / "ai-log-test.sqlite3")
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
import tenancy
tenancy.DB_PATH = Path(os.environ["DB_PATH"])
tenancy.FERNET_KEY = os.environ["FERNET_KEY"]
import ai_interaction_log

class AIInteractionLogTests(unittest.TestCase):
    def test_query_and_answer_are_encrypted_and_scoped_to_family(self):
        family_id = tenancy.create_family("Journal test", 9001)
        ai_interaction_log.record(family_id=family_id, actor_id=9001,
            query="Тестовый медицинский вопрос", answer="Краткий ответ", mode="analysis",
            provider="test-provider", model="test-model", duration_ms=42)
        with tenancy.connect() as conn:
            row = conn.execute("SELECT * FROM ai_interaction_logs WHERE family_id=?", (family_id,)).fetchone()
        self.assertIsNotNone(row)
        encrypted = bytes(row["payload_enc"])
        self.assertNotIn("Тестовый медицинский вопрос".encode(), encrypted)
        payload = json.loads(tenancy.cipher().decrypt(encrypted).decode())
        self.assertEqual(payload["query"], "Тестовый медицинский вопрос")
        self.assertEqual(payload["answer"], "Краткий ответ")
        self.assertEqual(row["duration_ms"], 42)

if __name__ == "__main__":
    unittest.main()
