"""Encrypted, source-linked patient memory derived deterministically from the family archive.

This module does not diagnose or infer new medical facts. It stores a compact, versioned
snapshot of structured information already extracted from documents and preserves source IDs.
"""
import hashlib
import hmac
import json
import logging
from datetime import date, datetime
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
            diagnoses.append({
                "text": text, "date": source["date"], "source": source,
                "page": item.get("page"), "evidence_type": "mentioned_in_document",
            })
        for item in (analysis.get("medications") or [])[:100]:
            text = _clean_text(item.get("text"), 500)
            if not text:
                continue
            key = (source["document_id"], "medication", text.casefold())
            if key in seen:
                continue
            seen.add(key)
            medications.append({
                "text": text, "date": source["date"], "source": source,
                "page": item.get("page"), "evidence_type": "mentioned_in_document",
            })
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
            lab_results.append({
                "name": name, "value": value, "unit": unit or None,
                "date": source["date"], "source": source,
                "page": item.get("page"), "source_line": _clean_text(item.get("source"), 350),
                "evidence_type": "extracted_result_needs_original_verification",
            })

    records.sort(key=lambda x: (_date_key(x.get("date")), x["document_id"]), reverse=True)
    diagnoses.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)
    medications.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)
    lab_results.sort(key=lambda x: (_date_key(x.get("date")), x["source"]["document_id"]), reverse=True)

    # Store a bounded summary but retain a complete, encrypted list of source document IDs.
    snapshot = {
        "schema_version": 1,
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
        "limitations": [
            "Сведения извлечены из документов и не являются независимо подтверждённым диагнозом.",
            "Результаты OCR и извлечённые показатели необходимо сверять с оригиналом.",
            "Отсутствие записи в памяти не доказывает отсутствие заболевания или назначения.",
            "Неизвестные даты не восстанавливаются предположением.",
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
    # A keyed fingerprint avoids exposing a plain hash of low-entropy medical facts in SQLite.
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
            "SELECT source_fingerprint,snapshot_enc FROM patient_memory_snapshots WHERE family_id=? AND patient_id=?",
            (fid, int(pid)),
        ).fetchone()
        if existing and existing["source_fingerprint"] == fingerprint:
            try:
                return json.loads(crypt.decrypt(existing["snapshot_enc"]).decode("utf-8"))
            except Exception:
                logging.warning("Patient memory snapshot could not be decrypted; rebuilding it")
        conn.execute(
            """INSERT INTO patient_memory_snapshots
               (family_id,patient_id,snapshot_enc,source_ids_enc,source_fingerprint,schema_version,updated_at)
               VALUES(?,?,?,?,?,1,?)
               ON CONFLICT(family_id,patient_id) DO UPDATE SET
                 snapshot_enc=excluded.snapshot_enc, source_ids_enc=excluded.source_ids_enc,
                 source_fingerprint=excluded.source_fingerprint, schema_version=1, updated_at=excluded.updated_at""",
            (
                fid, int(pid),
                crypt.encrypt(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")),
                crypt.encrypt(json.dumps(source_ids).encode("utf-8")),
                fingerprint, now,
            ),
        )
    return snapshot

def get_snapshot(fid: int, patient: str) -> dict:
    """Refresh from the source archive before returning the current memory snapshot."""
    return refresh(fid, patient)

def to_context(snapshot: dict, max_chars: int = 8500) -> str:
    """Format memory for a consented model request, retaining source IDs for citations."""
    lines = [
        "СТРУКТУРИРОВАННАЯ ПАМЯТЬ ПАЦИЕНТА (производная от документов; не считать диагнозы независимо подтверждёнными):",
        "Пациент: " + str(snapshot.get("patient") or "не указан"),
        "Дата рождения в карточке: " + str((snapshot.get("profile") or {}).get("birth_date") or "не указана"),
        "Документов в архиве: " + str(snapshot.get("document_count", 0)),
        "Упомянутые диагнозы/состояния (сначала сверить источник):",
    ]
    for item in snapshot.get("diagnoses_mentioned", [])[:60]:
        src = item.get("source") or {}
        lines.append(
            "- " + str(item.get("date") or "дата не указана") + ": " + str(item.get("text") or "")
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
        lines.append(
            "- " + str(item.get("date") or "дата не указана") + ": " + str(item.get("name") or "")
            + " = " + str(item.get("value") or "") + " " + str(item.get("unit") or "")
            + " [источник ID " + str(src.get("document_id")) + ", стр. " + str(item.get("page") or "?") + "]"
        )
    lines.append("Последние документы:")
    for item in snapshot.get("documents", [])[:30]:
        lines.append(
            "- ID " + str(item.get("document_id")) + " | " + str(item.get("date") or "дата не указана")
            + " | " + str(item.get("kind") or "") + " | " + str(item.get("name") or "")
        )
    lines.extend(snapshot.get("limitations", []))
    return "\n".join(lines)[:max(500, int(max_chars))]
