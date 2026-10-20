"""Persistent, versioned account-level opt-in for external medical AI processing.

Authentication alone is not consent. The grant is explicit, stored server-side,
and can be revoked. A consent-version change invalidates older grants.
"""
from datetime import datetime, timezone

import tenancy

CONSENT_VERSION = "external-medical-ai-v1-2026-10-15"


def _ensure_table():
    with tenancy.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_external_consent (
                user_id INTEGER PRIMARY KEY,
                granted INTEGER NOT NULL DEFAULT 0 CHECK (granted IN (0, 1)),
                consent_version TEXT NOT NULL,
                granted_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )


def get(user_id):
    """Return the current consent state for a stable authenticated user ID."""
    _ensure_table()
    with tenancy.connect() as connection:
        row = connection.execute(
            "SELECT granted, consent_version, granted_at, updated_at "
            "FROM ai_external_consent WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
    granted = bool(row and row["granted"] and row["consent_version"] == CONSENT_VERSION)
    return {
        "granted": granted,
        "version": CONSENT_VERSION,
        "granted_at": row["granted_at"] if granted else None,
        "updated_at": row["updated_at"] if row else None,
    }


def set_consent(user_id, granted):
    """Grant or revoke consent. Caller must only pass an explicit boolean."""
    if not isinstance(granted, bool):
        raise ValueError("granted must be a boolean")
    _ensure_table()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with tenancy.connect() as connection:
        if granted:
            connection.execute(
                """
                INSERT INTO ai_external_consent
                    (user_id, granted, consent_version, granted_at, updated_at)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    granted = 1,
                    consent_version = excluded.consent_version,
                    granted_at = excluded.granted_at,
                    updated_at = excluded.updated_at
                """,
                (int(user_id), CONSENT_VERSION, now, now),
            )
        else:
            connection.execute(
                """
                INSERT INTO ai_external_consent
                    (user_id, granted, consent_version, granted_at, updated_at)
                VALUES (?, 0, ?, NULL, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    granted = 0,
                    consent_version = excluded.consent_version,
                    granted_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (int(user_id), CONSENT_VERSION, now),
            )
    return get(user_id)
