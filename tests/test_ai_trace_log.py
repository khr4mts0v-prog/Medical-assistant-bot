import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_trace_log


class AITraceLogTests(unittest.TestCase):
    def test_trace_writes_plaintext_jsonl_with_shared_trace_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"AI_TRACE_LOG_PATH": str(Path(tmp) / "trace.log")}):
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


if __name__ == "__main__":
    unittest.main()