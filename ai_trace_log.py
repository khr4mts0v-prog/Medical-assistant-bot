"""Privacy-preserving structured trace events for AI archive requests."""
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

_lock = threading.Lock()
_handler = None


def _logger():
    global _handler
    name = "medical_ai_trace"
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if _handler is None:
        path = Path(os.getenv("AI_TRACE_LOG_PATH", "/app/data/ai_trace.log"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=4, encoding="utf-8", delay=False)
            # Full prompts and model responses can contain medical data. Restrict the
            # active log to the service account (owner read/write only).
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            handler.setFormatter(logging.Formatter("%(message)s"))
            _handler = handler
        except Exception:
            # Keep trace failures from breaking a medical request.
            _handler = False
    if _handler:
        if not logger.handlers:
            logger.addHandler(_handler)
        return logger
    return None


def fingerprint(value):
    """One-way identifier for patient/query/document labels; never stores source text."""
    value = " ".join(str(value or "").casefold().split())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else None


def start(*, family_id, actor_id, mode, query):
    trace_id = uuid.uuid4().hex
    emit(trace_id, "request.start", family_id=family_id, actor_id=actor_id, mode=mode,
         query_fp=fingerprint(query), query_chars=len(str(query or "")))
    return trace_id


def emit(trace_id, stage, **fields):
    record = {"ts": time.time(), "trace_id": str(trace_id or "")[:40], "stage": str(stage)[:80]}
    # Callers must pass only non-sensitive metadata, never query/OCR/answer text or names.
    for key, value in fields.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            record[str(key)[:60]] = value if not isinstance(value, str) else value[:300]
        elif isinstance(value, (list, tuple)):
            record[str(key)[:60]] = list(value)[:100]
        elif isinstance(value, dict):
            record[str(key)[:60]] = {str(k)[:60]: v for k, v in list(value.items())[:100]
                if v is None or isinstance(v, (str, int, float, bool))}
    logger = _logger()
    if logger:
        try:
            with _lock:
                logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        except Exception as exc:
            logging.warning("AI trace write failed (%s)", type(exc).__name__)


def emit_full(trace_id, stage, **fields):
    """Write explicitly requested plaintext diagnostic content to the restricted trace file."""
    record = {"ts": time.time(), "trace_id": str(trace_id or "")[:40], "stage": str(stage)[:80]}
    record.update(fields)
    logger = _logger()
    if logger:
        try:
            with _lock:
                logger.info(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")))
        except Exception as exc:
            logging.warning("AI trace write failed (%s)", type(exc).__name__)
