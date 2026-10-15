"""Patient memory: source-grounded, family-scoped facts with encrypted payloads.

The model may suggest facts, but persistence is performed by validated application code.
This module intentionally does not infer diagnoses or medication status.
"""
import json
import re
from datetime import date, datetime, timezone

import tenancy

ALLOWED_CATEGORIES = {
    "condition", "allergy", "pregnancy", "breastfeeding", "medication",
    "measurement", "lab_result", "procedure", "risk_factor", "preference",
    "other",
}
ALLOWED_STATUSES = {"user_reported", "documented", "confirmed", "uncertain", "disputed", "superseded"}
MAX_VALUE_LENGTH = 2000
MAX_SOURCE_LENGTH = 500
MAX_FACTS_PER_CONTEXT = 40


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value, limit):
    return " ".join(str(value or "").split()).strip()[:limit]


def _validate_fact(fact):
    if not isinstance(fact, dict):
        raise ValueError("Факт должен быть объектом")
    category = _clean_text(fact.get("category"), 40).lower()
    if category not in ALLOWED_CATEGORIES:
        raise ValueError("Неизвестная категория медицинского факта")
    key = _clean_text(fact.get("key"), 120)
    value = _clean_text(fact.get("value"), MAX_VALUE_LENGTH)
    status = _clean_text(fact.get("status") or "uncertain", 30).lower()
    if not key or not value:
        raise ValueError("У факта должны быть название и значение")
    if status not in ALLOWED_STATUSES:
        raise ValueError("Недопустимый статус факта")
    # Dates are stored as user/document supplied strings, never guessed here.
    source_type = _clean_text(fact.get("source_type") or "conversation", 30).lower()
    if source_type not in {"conversation", "document", "measurement", "user_correction", "external_reference"}:
        raise ValueError("Недопустимый тип источника")
    source_ref = _clean_text(fact.get("source_ref"), MAX_SOURCE_LENGTH)
    observed_at = _clean_text(fact.get("observed_at"), 40)
    valid_until = _clean_text(fact.get("valid_until"), 40)
    # Reject malformed supplied dates; absence remains explicitly unknown.
    for field_name, value_date in (("observed_at", observed_at), ("valid_until", valid_until)):
        if value_date:
            try:
                date.fromisoformat(value_date[:10])
            except ValueError as exc:
                raise ValueError("Некорректная дата " + field_name) from exc
    return {
        "category": category, "key": key, "value": value, "status": status,
        "source_type": source_type, "source_ref": source_ref,
        "observed_at": observed_at, "valid_until": valid_until,
        "confidence": max(0.0, min(1.0, float(fact.get("confidence", 0.5)))),
        "notes": _clean_text(fact.get("notes"), 1000),
    }


def _ensure_schema():
    with tenancy.connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER NOT NULL,
                patient TEXT NOT NULL COLLATE NOCASE,
                category TEXT NOT NULL,
                fact_key TEXT NOT NULL COLLATE NOCASE,
                payload_enc BLOB NOT NULL,
                status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                observed_at TEXT,
                valid_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                supersedes_id INTEGER,
                FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_patient ON patient_memory_facts(family_id, patient, category, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_dates ON patient_memory_facts(family_id, patient, observed_at)")


def save_fact(family_id, patient, fact, supersedes_id=None):
    """Save one fact. Caller must already authorize family_id and patient."""
    _ensure_schema()
    patient = _clean_text(patient, 100)
    if not patient:
        raise ValueError("Не указан пациент")
    data = _validate_fact(fact)
    payload = tenancy.cipher().encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    now = _now()
    with tenancy.connect() as conn:
        if supersedes_id is not None:
            old = conn.execute(
                "SELECT id FROM patient_memory_facts WHERE id=? AND family_id=? AND patient=? COLLATE NOCASE",
                (int(supersedes_id), int(family_id), patient),
            ).fetchone()
            if not old:
                raise ValueError("Заменяемый факт не найден у этого пациента")
            conn.execute(
                "UPDATE patient_memory_facts SET status='superseded', updated_at=? WHERE id=?",
                (now, int(supersedes_id)),
            )
        cur = conn.execute("""
            INSERT INTO patient_memory_facts
              (family_id, patient, category, fact_key, payload_enc, status, source_type,
               source_ref, observed_at, valid_until, created_at, updated_at, supersedes_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(family_id), patient, data["category"], data["key"], payload, data["status"],
            data["source_type"], data["source_ref"], data["observed_at"], data["valid_until"],
            now, now, int(supersedes_id) if supersedes_id is not None else None,
        ))
        return int(cur.lastrowid)


def list_facts(family_id, patient, include_superseded=False, limit=100):
    """Return decrypted facts only for the exact authorized family and patient."""
    _ensure_schema()
    limit = max(1, min(int(limit), 500))
    sql = "SELECT * FROM patient_memory_facts WHERE family_id=? AND patient=? COLLATE NOCASE"
    params = [int(family_id), _clean_text(patient, 100)]
    if not include_superseded:
        sql += " AND status!='superseded'"
    sql += " ORDER BY CASE status WHEN 'confirmed' THEN 0 WHEN 'documented' THEN 1 WHEN 'user_reported' THEN 2 ELSE 3 END, observed_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with tenancy.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        try:
            payload = json.loads(tenancy.cipher().decrypt(row["payload_enc"]).decode("utf-8"))
        except Exception:
            # Never expose ciphertext or silently fabricate a fact.
            continue
        result.append({"id": int(row["id"]), "family_id": int(row["family_id"]),
                       "patient": row["patient"], **payload,
                       "created_at": row["created_at"], "updated_at": row["updated_at"],
                       "supersedes_id": row["supersedes_id"]})
    return result


def build_context(family_id, patient, query="", limit=MAX_FACTS_PER_CONTEXT):
    """Build a bounded prompt context; safety-critical facts are prioritized."""
    facts = list_facts(family_id, patient, limit=500)
    q_tokens = set(re.findall(r"[0-9a-zа-яё-]{3,}", _clean_text(query, 1200).casefold().replace("ё", "е")))
    safety_categories = {"allergy", "pregnancy", "breastfeeding", "medication", "condition", "risk_factor"}
    ranked = []
    today = date.today()
    for fact in facts:
        valid_until = fact.get("valid_until")
        expired = False
        if valid_until:
            try:
                expired = date.fromisoformat(valid_until[:10]) < today
            except ValueError:
                expired = False
        tokens = set(re.findall(r"[0-9a-zа-яё-]{3,}",
                                (fact["key"] + " " + fact["value"] + " " + fact.get("notes", "")).casefold().replace("ё", "е")))
        relevance = len(q_tokens & tokens)
        # Expired facts are retained in history but not presented as current state.
        if expired:
            continue
        ranked.append((fact["category"] in safety_categories, relevance, fact["status"] == "confirmed",
                       fact.get("observed_at") or "", fact))
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    selected = [item[-1] for item in ranked[:max(1, min(int(limit), MAX_FACTS_PER_CONTEXT))]]
    if not selected:
        return ""
    lines = [
        "ПАМЯТЬ О ПАЦИЕНТЕ (контекст для проверки, не замена исходным документам):",
        "Каждый факт содержит статус и происхождение. Не превращай неопределённые факты в подтверждённые.",
        "Не считай старое назначение доказательством текущего приёма лекарства.",
    ]
    for fact in selected:
        source = fact.get("source_ref") or "источник не указан"
        observed = fact.get("observed_at") or "дата наблюдения неизвестна"
        lines.append(
            "- [{category}; статус={status}; источник={source_type}: {source}; дата={observed}; "
            "уверенность={confidence:.2f}] {key}: {value}".format(
                category=fact["category"], status=fact["status"], source_type=fact["source_type"],
                source=source, observed=observed, confidence=fact["confidence"],
                key=fact["key"], value=fact["value"])
        )
        if fact.get("notes"):
            lines.append("  Примечание: " + fact["notes"])
    return "\n".join(lines)[:12000]


def update_status(family_id, patient, fact_id, status):
    """Change status without deleting history; only facts in this family/patient can be changed."""
    if status not in ALLOWED_STATUSES:
        raise ValueError("Недопустимый статус факта")
    _ensure_schema()
    with tenancy.connect() as conn:
        cur = conn.execute(
            "UPDATE patient_memory_facts SET status=?, updated_at=? WHERE id=? AND family_id=? AND patient=? COLLATE NOCASE",
            (status, _now(), int(fact_id), int(family_id), _clean_text(patient, 100)),
        )
        if cur.rowcount != 1:
            raise ValueError("Факт не найден у этого пациента")
