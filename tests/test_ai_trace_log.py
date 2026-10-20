import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_trace_log


class AITraceLogTests(unittest.TestCase):
    def test_trace_writes_plaintext_jsonl_with_shared_trace_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"AI_TRACE_LOG_PATH": str(Path(tmp) / "trace.log"), "AI_TRACE_FULL_CONTENT_ENABLED": "true"}):
                with patch.object(ai_trace_log, "_handler", None):
                    trace_id = ai_trace_log.start(family_id=7, actor_id=9, mode="analysis", query="вопрос тест")
                    ai_trace_log.emit_full(trace_id, "request.raw", query="вопрос тест", context="фрагмент OCR")
                    for handler in ai_trace_log.logging.getLogger("medical_ai_trace").handlers[:]:
                        handler.close()
                        ai_trace_log.logging.getLogger("medical_ai_trace").removeHandler(handler)
                    ai_trace_log._handler = None
                rows = [json.loads(line) for line in (Path(tmp) / "trace.log").read_text().splitlines()]
            self.assertEqual([row["trace_id"] for row in rows], [trace_id, trace_id])
            self.assertEqual(rows[1]["query"], "вопрос тест")
            self.assertEqual(rows[1]["context"], "фрагмент OCR")
            self.assertEqual(rows[1]["stage"], "request.raw")

    def test_full_trace_payload_is_suppressed_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "trace.log"
            with patch.dict("os.environ", {"AI_TRACE_LOG_PATH": str(trace_path), "AI_TRACE_FULL_CONTENT_ENABLED": "false"}, clear=False):
                with patch.object(ai_trace_log, "_handler", None):
                    trace_id = ai_trace_log.start(family_id=7, actor_id=9, mode="analysis", query="private question")
                    ai_trace_log.emit_full(trace_id, "request.raw", query="SECRET_MEDICAL_TEXT", context="SECRET_OCR")
                    logger = ai_trace_log.logging.getLogger("medical_ai_trace")
                    for handler in logger.handlers[:]:
                        handler.close()
                        logger.removeHandler(handler)
                    ai_trace_log._handler = None
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
