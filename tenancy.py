"""Multi-family identity and encrypted Yandex OAuth token storage.

This module is groundwork for tenant isolation. Document queries must also be
scoped by family_id before this is enabled with real medical records.
"""
import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = Path(os.getenv("DB_PATH", "data/archive.sqlite3"))
FERNET_KEY = os.getenv("FERNET_KEY", "").strip()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _cipher():
    if not FERNET_KEY:
        raise RuntimeError("FERNET_KEY must be configured before storing cloud tokens")
    try:
        return Fernet(FERNET_KEY.encode())
    except Exception as exc:
        raise RuntimeError("FERNET_KEY is invalid; generate a Fernet key") from exc


def init():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_telegram_id INTEGER NOT NULL,
            yadisk_token_enc BLOB,
            yadisk_account_label TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS family_members (
            family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            telegram_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('owner','admin','member')),
            joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (family_id, telegram_id)
        );
        CREATE INDEX IF NOT EXISTS family_members_telegram
            ON family_members(telegram_id);
        """)


def create_family(name, owner_telegram_id):
    init()
    clean = " ".join((name or "").split())[:80]
    if not clean:
        raise ValueError("Family name cannot be empty")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO families(name, owner_telegram_id) VALUES(?, ?)",
            (clean, int(owner_telegram_id)),
        )
        family_id = cur.lastrowid
        conn.execute(
            "INSERT INTO family_members(family_id, telegram_id, role) VALUES(?, ?, 'owner')",
            (family_id, int(owner_telegram_id)),
        )
        return family_id


def families_for_user(telegram_id):
    init()
    with _connect() as conn:
        rows = conn.execute("""
            SELECT f.id, f.name, m.role, f.yadisk_account_label
            FROM families f JOIN family_members m ON m.family_id=f.id
            WHERE m.telegram_id=? ORDER BY f.name
        """, (int(telegram_id),)).fetchall()
        return [dict(row) for row in rows]


def add_member(family_id, telegram_id, role="member", actor_telegram_id=None):
    if role not in ("admin", "member"):
        raise ValueError("Only admin or member can be assigned here")
    with _connect() as conn:
        actor = conn.execute(
            "SELECT role FROM family_members WHERE family_id=? AND telegram_id=?",
            (int(family_id), int(actor_telegram_id)),
        ).fetchone()
        if not actor or actor["role"] not in ("owner", "admin"):
            raise PermissionError("Only a family owner/admin can invite members")
        conn.execute(
            "INSERT OR REPLACE INTO family_members(family_id, telegram_id, role) VALUES(?, ?, ?)",
            (int(family_id), int(telegram_id), role),
        )


def role_for_user(family_id, telegram_id):
    init()
    with _connect() as conn:
        row = conn.execute(
            "SELECT role FROM family_members WHERE family_id=? AND telegram_id=?",
            (int(family_id), int(telegram_id)),
        ).fetchone()
        return row["role"] if row else None


def save_yadisk_token(family_id, token, account_label=""):
    if not token or not token.strip():
        raise ValueError("Empty Yandex Disk access token")
    encrypted = _cipher().encrypt(token.strip().encode())
    with _connect() as conn:
        conn.execute(
            "UPDATE families SET yadisk_token_enc=?, yadisk_account_label=? WHERE id=?",
            (encrypted, (account_label or "")[:160], int(family_id)),
        )


def get_yadisk_token(family_id):
    init()
    with _connect() as conn:
        row = conn.execute(
            "SELECT yadisk_token_enc FROM families WHERE id=?", (int(family_id),)
        ).fetchone()
    if not row or not row["yadisk_token_enc"]:
        return None
    try:
        return _cipher().decrypt(row["yadisk_token_enc"]).decode()
    except InvalidToken as exc:
        raise RuntimeError("Cannot decrypt family Yandex token; check FERNET_KEY") from exc
