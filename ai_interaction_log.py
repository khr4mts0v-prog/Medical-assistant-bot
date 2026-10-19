"""Encrypted, family-scoped AI interaction journal for quality evaluation."""
import json
import logging
from datetime import datetime, timezone

import tenancy

_RETENTION_DAYS = 90
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_interaction_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  actor_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER,
  payload_enc BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_interaction_logs_family_date ON ai_interaction_logs(family_id, created_at);
"""

def record(*, family_id, actor_id, query, answer, mode, provider="", model="", status="ok", duration_ms=None):
    """Store only the user prompt and final visible answer, encrypted at rest."""
    try:
        tenancy.init()
        payload = json.dumps({"query": str(query or "")[:1200], "answer": str(answer or "")[:8000]}, ensure_ascii=False).encode("utf-8")
        encrypted = tenancy.cipher().encrypt(payload)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with tenancy.connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO ai_interaction_logs(family_id,actor_id,created_at,mode,provider,model,status,duration_ms,payload_enc) VALUES(?,?,?,?,?,?,?,?,?)",
                (int(family_id), int(actor_id), now, str(mode or "unknown")[:40], str(provider or "")[:40], str(model or "")[:160], str(status or "ok")[:30], int(duration_ms) if duration_ms is not None else None, encrypted),
            )
            conn.execute("DELETE FROM ai_interaction_logs WHERE created_at < datetime('now', ?)", (f"-{_RETENTION_DAYS} days",))
    except Exception as exc:
        # Evaluation logging must never break a medical answer; never log payloads to app logs.
        logging.warning("AI interaction journal write failed (%s)", type(exc).__name__)