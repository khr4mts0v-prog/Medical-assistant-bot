#!/usr/bin/env python3
"""Fail-closed environment preflight for testing or production deployments."""
import argparse
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def parse_env(path):
    values = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def validate(values, mode="production"):
    if mode not in {"testing", "production"}:
        return ["mode must be testing or production."]
    errors = []
    for key in ("WEB_USERNAME", "WEB_PASSWORD", "WEB_SESSION_SECRET", "FERNET_KEY",
                "DEMO_USERNAME", "DEMO_PASSWORD", "DOCUMENT_STORAGE_BACKEND"):
        if key not in values:
            errors.append(f"{key} must be explicitly present in .env (use an empty value to disable demo login).")

    username = values.get("WEB_USERNAME", "").strip()
    password = values.get("WEB_PASSWORD", "")
    if not username:
        errors.append("WEB_USERNAME must not be empty.")
    if len(password) < 20:
        errors.append("WEB_PASSWORD must contain at least 20 characters.")
    if len(values.get("WEB_SESSION_SECRET", "")) < 32:
        errors.append("WEB_SESSION_SECRET must contain at least 32 characters.")

    fernet_key = values.get("FERNET_KEY", "").strip()
    try:
        Fernet(fernet_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        errors.append("FERNET_KEY must be a valid Fernet key.")

    demo_user = values.get("DEMO_USERNAME", "").strip()
    demo_password = values.get("DEMO_PASSWORD", "")
    if bool(demo_user) != bool(demo_password):
        errors.append("DEMO_USERNAME and DEMO_PASSWORD must both be empty to disable demo login, or both be configured.")
    elif demo_user and demo_password:
        if mode == "production":
            if demo_user.casefold() == "test" or demo_password.casefold() == "test":
                errors.append("Default demo credentials are forbidden for production; disable demo login or set unique credentials.")
            if len(demo_password) < 20:
                errors.append("DEMO_PASSWORD must contain at least 20 characters when demo login is enabled.")
        if demo_user == username and demo_password == password:
            errors.append("Demo credentials must differ from the main web account.")

    backend = values.get("DOCUMENT_STORAGE_BACKEND", "").strip().casefold()
    if backend not in {"local", "yandex"}:
        errors.append("DOCUMENT_STORAGE_BACKEND must be explicitly set to local or yandex.")
    elif mode == "production" and backend == "local" and values.get("LOCAL_STORAGE_AT_REST_PROTECTED", "").strip().casefold() != "true":
        errors.append(
            "Local originals and OCR sidecars are plaintext files. Verify host-volume encryption or equivalent protection, "
            "then explicitly set LOCAL_STORAGE_AT_REST_PROTECTED=true."
        )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--mode", choices=("testing", "production"), default="production")
    args = parser.parse_args()
    path = Path(args.env_file)
    if not path.is_file() or not os.access(path, os.R_OK):
        print("FAIL: .env file is missing or unreadable.", file=sys.stderr)
        return 2
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        print("FAIL: .env permissions must deny all group/other access (recommended mode 600).", file=sys.stderr)
        return 2
    try:
        errors = validate(parse_env(path), mode=args.mode)
    except (OSError, UnicodeError) as exc:
        print(f"FAIL: could not read .env ({type(exc).__name__}).", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print("FAIL: " + error, file=sys.stderr)
        return 1
    print(f"PASS: {args.mode} environment preflight. Secret values were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
