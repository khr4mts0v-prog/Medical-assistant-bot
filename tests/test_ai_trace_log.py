import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_trace_log


class AITraceLogTests(unittest.TestCase):
    def reset_logger(self):
        logger = ai_trace_log.logging.getLogger("medical_ai_trace")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        ai_trace_log._handler = None

    def test_trace_writes_plaintext_jsonl_only_after_explicit_opt_in(self):
        self.reset_logger()
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.log"
            with patch.dict("os.environ", {"AI_TRACE_LOG_PATH": str(trace_path), "AI_TRACE_FULL_CONTENT_ENABLED": "true"}):
                trace_id = ai_trace_log.start(family_id=7, actor_id=9, mode="analysis", query="вопрос тест")
                ai_trace_log.emit_full(trace_id, "request.raw", query="вопрос тест", context="фрагмент OCR")
                self.reset_logger()
            rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["trace_id"] for row in rows], [trace_id, trace_id])
        self.assertEqual(rows[1]["query"], "вопрос тест")
        self.assertEqual(rows[1]["context"], "фрагмент OCR")
        self.assertEqual(rows[1]["stage"], "request.raw")

    def test_full_trace_payload_is_suppressed_by_default(self):
        self.reset_logger()
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.log"
            with patch.dict("os.environ", {"AI_TRACE_LOG_PATH": str(trace_path), "AI_TRACE_FULL_CONTENT_ENABLED": "false"}):
                trace_id = ai_trace_log.start(family_id=7, actor_id=9, mode="analysis", query="private question")
                ai_trace_log.emit_full(trace_id, "request.raw", query="SECRET_MEDICAL_TEXT", context="SECRET_OCR")
                self.reset_logger()
            raw = trace_path.read_text(encoding="utf-8")
            rows = [json.loads(line) for line in raw.splitlines()]
        self.assertNotIn("SECRET_MEDICAL_TEXT", raw)
        self.assertNotIn("SECRET_OCR", raw)
        self.assertEqual(rows[1]["stage"], "request.raw.content_suppressed")
        self.assertTrue(rows[1]["content_suppressed"])
        self.assertEqual(rows[1]["field_names"], ["context", "query"])
        self.assertEqual(rows[1]["trace_id"], trace_id)


if __name__ == "__main__":
    unittest.main()
