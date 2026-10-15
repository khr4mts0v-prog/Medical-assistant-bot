"""Encrypted, source-linked patient memory derived deterministically from the family archive.

This module does not diagnose or infer new medical facts. It stores a compact, versioned
snapshot of structured information already extracted from documents and preserves source IDs.
"""
import hashlib
import hmac
import json
import secrets
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

import database as db
import tenancy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_memory_snapshots (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    snapshot_enc BLOB NOT NULL,
    source_ids_enc BLOB NOT NULL,
    source_fingerprint TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (family_id, patient_id)
);
CREATE INDEX IF NOT EXISTS patient_memory_family_updated
    ON patient_memory_snapshots(family_id, updated_at);
CREATE TABLE IF NOT EXISTS patient_memory_edits (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    source_document_id INTEGER NOT NULL,
    payload_enc BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (family_id, patient_id, fact_key)
);
CREATE INDEX IF NOT EXISTS patient_memory_edits_patient
    ON patient_memory_edits(family_id, patient_id);
CREATE TABLE IF NOT EXISTS patient_memory_manual_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    payload_enc BLOB NOT NULL,
    created_by INTEGER NOT NULL,
    updated_by INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS patient_memory_manual_patient
    ON patient_memory_manual_facts(family_id, patient_id, status, updated_at);
"""

def init() -> None:
    """Create the memory table idempotently; existing archive data is untouched."""
    tenancy.init()
    with tenancy.connect() as conn:
        conn.executescript(_SCHEMA)

def _date_key(value: Any):
    text = str(value or "").strip()
    if not text:
        return date.min
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return date.min

def _clean_text(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]

def _source_ref(row: dict) -> dict:
    return {
        "document_id": int(row["id"]),
        "name": _clean_text(row.get("name") or "Документ без названия", 255),
        "date": _clean_text(row.get("date"), 40) or None,
        "kind": _clean_text(row.get("kind") or "не определён", 100),
    }

def _fact_key(category: str, item: dict) -> str:
    source = item.get("source") or {}
    identity = {
        "category": category,
        "document_id": source.get("document_id"),
        "page": item.get("page"),
        "text": item.get("text"),
        "name": item.get("name"),
        "value": item.get("value"),
        "unit": item.get("unit"),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hmac.new(tenancy.FERNET_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()

def _numeric_value(value: Any):
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text or text.startswith(("<", ">", "≤", "≥")):
        return None
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None

def _build_lab_trends(lab_results: list[dict]) -> list[dict]:
    """Compare only numeric results with the same normalized marker and explicit unit."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in lab_results:
        name = " ".join(re.sub(r"[^0-9a-zа-яё]+", " ", str(item.get("name") or "").casefold().replace("ё", "е")).split())
        unit = " ".join(str(item.get("unit") or "").casefold().split())
        value = _numeric_value(item.get("value"))
        if not name or not unit or value is None or _date_key(item.get("date")) == date.min:
            continue
        groups.setdefault((name, unit), []).append({**item, "_numeric": value})

    trends = []
    for (name_key, unit_key), items in groups.items():
        by_date = {}
        ambiguous_dates = set()
        for item in items:
            day = _date_key(item.get("date"))
            entry = {
                "date": item.get("date"),
                "value": str(item.get("value")),
                "numeric": item["_numeric"],
                "marker_name": item.get("name"),
                "source": item.get("source") or {},
            }
            if day in by_date and by_date[day]["numeric"] != entry["numeric"]:
                ambiguous_dates.add(day)
            else:
                by_date[day] = entry
        valid = [
            by_date[day] for day in sorted(by_date, reverse=True)
            if day not in ambiguous_dates
        ]
        if len(valid) < 2:
            continue
        latest, previous = valid[0], valid[1]
        delta = latest["numeric"] - previous["numeric"]
        direction = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
        trends.append({
            "name": latest.get("marker_name") or name_key,
            "unit": unit_key,
            "latest": {k: latest[k] for k in ("date", "value", "source")},
            "previous": {k: previous[k] for k in ("date", "value", "source")},
            "absolute_change": format(delta.normalize(), "f"),
            "direction": direction,
        })
    trends.sort(key=lambda item: (_date_key(item["latest"].get("date")), item["name"]), reverse=True)
    return trends[:100]

def _build_snapshot(fid: int, patient: str, rows: list[dict], profile: dict | None = None) -> dict:
    records = []
    diagnoses = []
    medications = []
    lab_results = []
    seen = set()

    for row in rows:
        analysis = row.get("analysis") or {}
        source = _source_ref(row)
        records.append(source)
        for item in (analysis.get("diagnoses") or [])[:100]:
            text = _clean_text(item.get("text"), 500)
            if not text:
                continue
            key = (source["document_id"], "diagnosis", text.casefold())
            if key in seen:
                continue
            seen.add(key)
            fact = {
                "text": text, "date": source["date"], "source": source,
                "page": item.get("page"), "evidence_type": "mentioned_in_document",
            }
            fact["fact_key"] = _fact_key("diagnosis", fact)
            diagnoses.append(fact)
        for item in (analysis.get("medications") or [])[:100]:
            text = _clean_text(item.get("text"), 500)
            if not text:
                continue
            key = (source["document_id"], "medication", text.casefold())
            if key in seen:
                continue
            seen.add(key)
            fact = {
                "text": text, "date": source["date"], "source": source,
                "page": item.get("page"), "evidence_type": "mentioned_in_document",
            }
            fact["fact_key"] = _fact_key("medication", fact)
            medications.append(fact)
        for item in (analysis.get("lab_results") or [])[:250]:
            name = _clean_text(item.get("name"), 160)
            value = _clean_text(item.get("value"), 100)
            unit = _clean_text(item.get("unit"), 80)
            if not name or not value:
                continue
            key = (source["document_id"], "lab", name.casefold(), value, unit)
            if key in seen:
                continue
            seen.add(key)
            fact = {
                "name": name, "value": value, "unit": unit or None,
                "date": source["date"], "source": source,
                "page": item.get("page"), "source_line": _clean_text(item.get("source"), 350),
                "evidence_type": "extracted_result_needs_original_verification",
            }
            fact["fact_key"] = _fact_key("lab_result", fact)
            lab_results.append(fact)

    records.sort(key=lambda x: (_date_key(x.get("date")), x["document_id"]), reverse=True)
    diagnoses.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)
    medications.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)
    lab_results.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)
    lab_trends = _build_lab_trends(lab_results)

    # Store a bounded summary but retain a complete, encrypted list of source document IDs.
    snapshot = {
        "schema_version": 2,
        "family_id": int(fid),
        "patient": patient,
        "profile": {
            "name": patient,
            "birth_date": _clean_text((profile or {}).get("birth_date"), 40) or None,
        },
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "document_count": len(records),
        "documents": records[:500],
        "diagnoses_mentioned": diagnoses[:300],
        "medications_mentioned": medications[:300],
        "lab_results": lab_results[:500],
        "lab_trends": lab_trends,
        "limitations": [
            "Сведения извлечены из документов и не являются независимо подтверждённым диагнозом.",
            "Результаты OCR и извлечённые показатели необходимо сверять с оригиналом.",
            "Отсутствие записи в памяти не доказывает отсутствие заболевания или назначения.",
            "Неизвестные даты не восстанавливаются предположением.",
            "Динамика рассчитывается только для числовых результатов с совпадающими единицами; сама по себе не устанавливает диагноз.",
        ],
    }
    fingerprint_payload = {
        "patient": patient,
        "profile": {"birth_date": _clean_text((profile or {}).get("birth_date"), 40) or None},
        "records": [
            {
                "id": int(row["id"]), "name": row.get("name"), "date": row.get("date"),
                "kind": row.get("kind"), "analysis": row.get("analysis") or {},
            }
            for row in rows
        ],
    }
    fingerprint_bytes = json.dumps(
        fingerprint_payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    # A keyed fingerprint prevents dictionary attacks against low-entropy medical facts in SQLite.
    fingerprint = hmac.new(
        tenancy.FERNET_KEY.encode("utf-8"), fingerprint_bytes, hashlib.sha256
    ).hexdigest()
    source_ids = sorted({int(row["id"]) for row in rows})
    return snapshot, source_ids, fingerprint

def refresh(fid: int, patient: str) -> dict:
    """Rebuild memory from current local archive documents and persist it encrypted."""
    init()
    fid = int(fid)
    patient = " ".join(str(patient or "").split())
    pid = db.patient_id(fid, patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    rows = db.search(fid, patient, "", limit=1000)
    profile = next(
        (record for record in db.patient_records(fid) if record["name"].casefold() == patient.casefold()),
        {},
    )
    snapshot, source_ids, fingerprint = _build_snapshot(fid, patient, rows, profile)
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    crypt = tenancy.cipher()
    with tenancy.connect() as conn:
        existing = conn.execute(
            "SELECT source_fingerprint,snapshot_enc,schema_version FROM patient_memory_snapshots WHERE family_id=? AND patient_id=?",
            (fid, int(pid)),
        ).fetchone()
        if existing and int(existing["schema_version"]) == 2 and existing["source_fingerprint"] == fingerprint:
            try:
                return json.loads(crypt.decrypt(existing["snapshot_enc"]).decode("utf-8"))
            except Exception:
                logging.warning("Patient memory snapshot could not be decrypted; rebuilding it")
        conn.execute(
            """INSERT INTO patient_memory_snapshots
               (family_id,patient_id,snapshot_enc,source_ids_enc,source_fingerprint,schema_version,updated_at)
               VALUES(?,?,?,?,?,2,?)
               ON CONFLICT(family_id,patient_id) DO UPDATE SET
                 snapshot_enc=excluded.snapshot_enc, source_ids_enc=excluded.source_ids_enc,
                 source_fingerprint=excluded.source_fingerprint, schema_version=2, updated_at=excluded.updated_at""",
            (
                fid, int(pid),
                crypt.encrypt(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")),
                crypt.encrypt(json.dumps(source_ids).encode("utf-8")),
                fingerprint, now,
            ),
        )
    return snapshot

def _load_edits(fid: int, pid: int) -> dict:
    with tenancy.connect() as conn:
        rows = conn.execute(
            "SELECT fact_key,payload_enc FROM patient_memory_edits WHERE family_id=? AND patient_id=?",
            (int(fid), int(pid)),
        ).fetchall()
    edits = {}
    crypt = tenancy.cipher()
    for row in rows:
        try:
            edits[row["fact_key"]] = json.loads(crypt.decrypt(row["payload_enc"]).decode("utf-8"))
        except Exception:
            logging.exception("Cannot decrypt patient memory correction")
    return edits

def _apply_edits(snapshot: dict, edits: dict) -> dict:
    result = dict(snapshot)
    for key, category in (
        ("diagnoses_mentioned", "diagnosis"),
        ("medications_mentioned", "medication"),
        ("lab_results", "lab_result"),
    ):
        visible = []
        for original in snapshot.get(key, []):
            item = dict(original)
            edit = edits.get(item.get("fact_key"))
            if edit and edit.get("action") == "ignore":
                continue
            if edit and edit.get("action") == "correct":
                if category in {"diagnosis", "medication"} and edit.get("replacement"):
                    item["original_text"] = item.get("text")
                    item["text"] = edit["replacement"]
                if category == "lab_result":
                    if edit.get("replacement"):
                        item["original_value"] = item.get("value")
                        item["value"] = edit["replacement"]
                    if "unit" in edit:
                        item["original_unit"] = item.get("unit")
                        item["unit"] = edit.get("unit") or None
                item["user_corrected"] = True
                item["correction_note"] = edit.get("note") or ""
            visible.append(item)
        result[key] = visible
    # Trends must be recalculated from corrected/visible results, not stale extracted values.
    result["lab_trends"] = _build_lab_trends(result.get("lab_results", []))
    return result

def get_snapshot(fid: int, patient: str) -> dict:
    """Refresh from source documents and overlay family-scoped, encrypted user corrections."""
    snapshot = refresh(fid, patient)
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    snapshot = _apply_edits(snapshot, _load_edits(fid, pid))
    snapshot["manual_facts"] = get_manual_facts(fid, patient)
    return snapshot

def _manual_payload(text: str, category: str, fact_date: str) -> dict:
    text = _clean_text(text, 2000)
    category = str(category or "note").strip()
    if category not in {"note", "diagnosis", "medication", "lab_result", "symptom"}:
        raise ValueError("Неизвестный тип ручной записи")
    if not text:
        raise ValueError("Введите текст факта")
    fact_date = _clean_text(fact_date, 40)
    if fact_date and _date_key(fact_date) == date.min:
        raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ")
    return {"text": text, "category": category, "date": fact_date or None}


def get_manual_facts(fid: int, patient: str, include_inactive: bool = False) -> list[dict]:
    """Return explicitly user-entered facts; payload is encrypted at rest."""
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    where_status = "" if include_inactive else " AND status='active'"
    with tenancy.connect() as conn:
        rows = conn.execute(
            "SELECT id,payload_enc,created_by,updated_by,status,created_at,updated_at "
            "FROM patient_memory_manual_facts WHERE family_id=? AND patient_id=?" + where_status +
            " ORDER BY updated_at DESC,id DESC",
            (int(fid), int(pid)),
        ).fetchall()
    facts = []
    crypt = tenancy.cipher()
    for row in rows:
        try:
            payload = json.loads(crypt.decrypt(row["payload_enc"]).decode("utf-8"))
        except Exception:
            logging.warning("Unable to decrypt manual patient memory fact id=%s", row["id"])
            continue
        facts.append({
            "id": int(row["id"]), **payload, "created_by": int(row["created_by"]),
            "updated_by": int(row["updated_by"]), "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "origin": "user_entered", "source": None,
        })
    return facts


def add_manual_fact(fid: int, patient: str, text: str, category: str,
                    fact_date: str, actor_id: int) -> int:
    """Add an encrypted, user-entered fact without inventing a document source."""
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    payload = _manual_payload(text, category, fact_date)
    encrypted = tenancy.cipher().encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with tenancy.connect() as conn:
        cur = conn.execute(
            """INSERT INTO patient_memory_manual_facts
               (family_id,patient_id,payload_enc,created_by,updated_by,status,created_at,updated_at)
               VALUES(?,?,?,?,?,'active',?,?)""",
            (int(fid), int(pid), encrypted, int(actor_id), int(actor_id), now, now),
        )
        return int(cur.lastrowid)


def update_manual_fact(fid: int, patient: str, fact_id: int, text: str,
                       category: str, fact_date: str, actor_id: int) -> None:
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    payload = _manual_payload(text, category, fact_date)
    encrypted = tenancy.cipher().encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with tenancy.connect() as conn:
        cur = conn.execute(
            """UPDATE patient_memory_manual_facts SET payload_enc=?,updated_by=?,updated_at=?
               WHERE id=? AND family_id=? AND patient_id=?""",
            (encrypted, int(actor_id), now, int(fact_id), int(fid), int(pid)),
        )
        if cur.rowcount != 1:
            raise ValueError("Ручная запись не найдена у выбранного пациента")


def delete_manual_fact(fid: int, patient: str, fact_id: int) -> None:
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    with tenancy.connect() as conn:
        cur = conn.execute(
            "DELETE FROM patient_memory_manual_facts WHERE id=? AND family_id=? AND patient_id=?",
            (int(fact_id), int(fid), int(pid)),
        )
        if cur.rowcount != 1:
            raise ValueError("Ручная запись не найдена у выбранного пациента")


def save_edit(fid: int, patient: str, fact_key: str, action: str,
              replacement: str = "", unit: str = "", note: str = "") -> None:
    """Save a correction/ignore decision only for a fact currently present for this patient."""
    if action not in {"correct", "ignore", "restore"}:
        raise ValueError("Неизвестное действие с записью")
    snapshot = refresh(fid, patient)
    pid = db.patient_id(int(fid), patient)
    if pid is None:
        raise ValueError("Пациент не найден в этом семейном архиве")
    fact = None
    category = None
    for list_key, candidate_category in (
        ("diagnoses_mentioned", "diagnosis"),
        ("medications_mentioned", "medication"),
        ("lab_results", "lab_result"),
    ):
        fact = next((item for item in snapshot.get(list_key, []) if hmac.compare_digest(str(item.get("fact_key") or ""), str(fact_key))), None)
        if fact:
            category = candidate_category
            break
    if not fact:
        raise ValueError("Запись памяти не найдена или уже изменилась; обновите страницу")
    if action == "restore":
        with tenancy.connect() as conn:
            conn.execute(
                "DELETE FROM patient_memory_edits WHERE family_id=? AND patient_id=? AND fact_key=?",
                (int(fid), int(pid), fact_key),
            )
        return
    payload = {"action": action, "note": _clean_text(note, 500)}
    if action == "correct":
        replacement = _clean_text(replacement, 500)
        if not replacement:
            raise ValueError("Введите исправленное значение")
        payload["replacement"] = replacement
        if category == "lab_result":
            payload["unit"] = _clean_text(unit, 80)
    crypt = tenancy.cipher()
    encrypted = crypt.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with tenancy.connect() as conn:
        conn.execute(
            """INSERT INTO patient_memory_edits(family_id,patient_id,fact_key,source_document_id,payload_enc,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(family_id,patient_id,fact_key) DO UPDATE SET
                 source_document_id=excluded.source_document_id,
                 payload_enc=excluded.payload_enc, updated_at=excluded.updated_at""",
            (int(fid), int(pid), fact_key, int((fact.get("source") or {}).get("document_id") or 0), encrypted, now),
        )

def to_context(snapshot: dict, max_chars: int = 8500) -> str:
    """Format memory for a consented model request, retaining source IDs for citations."""
    lines = [
        "СТРУКТУРИРОВАННАЯ ПАМЯТЬ ПАЦИЕНТА (производная от документов; не считать диагнозы независимо подтверждёнными):",
        "Пациент: " + str(snapshot.get("patient") or "не указан"),
        "Дата рождения в карточке: " + str((snapshot.get("profile") or {}).get("birth_date") or "не указана"),
        "Документов в архиве: " + str(snapshot.get("document_count", 0)),
        "РУЧНЫЕ ЗАПИСИ ПОЛЬЗОВАТЕЛЯ (не извлечены из документа; автор/дата сохранения указаны отдельно):",
    ]
    for item in snapshot.get("manual_facts", [])[:80]:
        lines.append(
            "- [" + str(item.get("category") or "note") + "] " + str(item.get("date") or "дата факта не указана")
            + ": " + str(item.get("text") or "")
            + " [внесено пользователем ID " + str(item.get("created_by")) + "; создано "
            + str(item.get("created_at") or "?") + "; обновлено " + str(item.get("updated_at") or "?")
            + "; статус " + str(item.get("status") or "active") + "; документ-источник отсутствует]"
        )
    lines.append("Упомянутые диагнозы/состояния (сначала сверить источник):"
    ]
    for item in snapshot.get("diagnoses_mentioned", [])[:60]:
        src = item.get("source") or {}
        correction = " [ИСПРАВЛЕНО ПОЛЬЗОВАТЕЛЕМ; исходное извлечение: " + str(item.get("original_text")) + "]" if item.get("user_corrected") else ""
        lines.append(
            "- " + str(item.get("date") or "дата не указана") + ": " + str(item.get("text") or "")
            + correction
            + " [источник ID " + str(src.get("document_id")) + ": " + str(src.get("name") or "") + "]"
        )
    lines.append("Упомянутые лекарства и назначения (не означает, что приём продолжается):")
    for item in snapshot.get("medications_mentioned", [])[:60]:
        src = item.get("source") or {}
        lines.append(
            "- " + str(item.get("date") or "дата не указана") + ": " + str(item.get("text") or "")
            + " [источник ID " + str(src.get("document_id")) + ": " + str(src.get("name") or "") + "]"
        )
    lines.append("Лабораторные результаты (значения и единицы не пересчитывались):")
    for item in snapshot.get("lab_results", [])[:100]:
        src = item.get("source") or {}
        correction = " [ИСПРАВЛЕНО ПОЛЬЗОВАТЕЛЕМ; исходное значение: " + str(item.get("original_value")) + " " + str(item.get("original_unit") or "") + "]" if item.get("user_corrected") else ""
        lines.append(
            "- " + str(item.get("date") or "дата не указана") + ": " + str(item.get("name") or "")
            + " = " + str(item.get("value") or "") + " " + str(item.get("unit") or "")
            + correction
            + " [источник ID " + str(src.get("document_id")) + ", стр. " + str(item.get("page") or "?") + "]"
        )
    lines.append("Сравнение двух последних числовых результатов с одинаковыми единицами:")
    for trend in snapshot.get("lab_trends", [])[:40]:
        latest = trend.get("latest") or {}
        previous = trend.get("previous") or {}
        latest_source = latest.get("source") or {}
        previous_source = previous.get("source") or {}
        lines.append(
            "- " + str(trend.get("name") or "") + ": " + str(previous.get("value") or "")
            + " -> " + str(latest.get("value") or "") + " " + str(trend.get("unit") or "")
            + "; изменение " + str(trend.get("absolute_change")) + " " + str(trend.get("unit") or "")
            + "; даты " + str(previous.get("date") or "?") + " -> " + str(latest.get("date") or "?")
            + "; источники ID " + str(previous_source.get("document_id")) + " и "
            + str(latest_source.get("document_id"))
        )
    lines.append("Последние документы:")
    for item in snapshot.get("documents", [])[:30]:
        lines.append(
            "- ID " + str(item.get("document_id")) + " | " + str(item.get("date") or "дата не указана")
            + " | " + str(item.get("kind") or "") + " | " + str(item.get("name") or "")
        )
    lines.extend(snapshot.get("limitations", []))
    return "\n".join(lines)[:max(500, int(max_chars))]
