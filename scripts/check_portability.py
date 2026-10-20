#!/usr/bin/env python3
"""Read-only portability preflight for a clean clone of Medical Assistant.

This check validates the presence of source/configuration needed to rebuild the
application. It does not read .env values, connect to production, or modify data.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "main.py",
    "webapp.py",
    "react_ui.py",
    "database.py",
    "tenancy.py",
    "ocr.py",
    "AIAnalise.py",
    "assistant_routes.py",
    "frontend/package.json",
    "frontend/src/main.tsx",
    "frontend/src/style.css",
    ".github/workflows/tests.yml",
    "DEPLOYMENT.md",
    "docs/PORTABILITY_HOME_SERVER.md",
)

FORBIDDEN_TRACKED_PARTS = (
    ".env",
    "data/",
)
FORBIDDEN_TRACKED_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".log")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")

    env_example = ROOT / ".env.example"
    if env_example.is_file():
        env_text = env_example.read_text(encoding="utf-8")
        for required in ("BOT_TOKEN=", "WEB_PASSWORD=", "WEB_SESSION_SECRET=", "FERNET_KEY="):
            if required not in env_text:
                errors.append(f".env.example missing variable declaration: {required[:-1]}")
        if any(marker in env_text for marker in ("pza_live_", "hf_", "ghp_", "github_pat_")):
            errors.append(".env.example appears to contain a token-like value; review manually")

    dockerfile = ROOT / "Dockerfile"
    if dockerfile.is_file():
        text = dockerfile.read_text(encoding="utf-8")
        for marker in ("FROM node:20-alpine AS frontend-build", "npm run build", "tesseract-ocr-rus", "tesseract-ocr-eng"):
            if marker not in text:
                errors.append(f"Dockerfile missing portability requirement: {marker}")

    compose = ROOT / "docker-compose.yml"
    if compose.is_file():
        text = compose.read_text(encoding="utf-8")
        for marker in ("medical-archive:", "medical-archive-web:", "./data:/app/data"):
            if marker not in text:
                errors.append(f"docker-compose.yml missing expected service/volume declaration: {marker}")
        if ".env" not in text:
            errors.append("docker-compose.yml does not reference a local .env file")

    git = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if git.returncode != 0:
        errors.append("cannot inspect tracked files (run this check inside a Git clone)")
    else:
        tracked = [item.decode("utf-8", "replace") for item in git.stdout.split(b"\0") if item]
        for name in tracked:
            normalized = name.replace("\\", "/")
            if normalized == ".env" or normalized.startswith(".env.") and normalized != ".env.example":
                errors.append(f"secret environment file is tracked: {name}")
            if normalized.startswith("data/") or "/data/" in normalized:
                errors.append(f"runtime data path is tracked: {name}")
            if Path(normalized).suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES:
                errors.append(f"database/log artifact is tracked: {name}")
            if Path(normalized).name.lower() in ("id_rsa", "id_ed25519", "credentials.json"):
                errors.append(f"potential credential file is tracked: {name}")

    if not (ROOT / "frontend/package-lock.json").exists():
        warnings.append("frontend/package-lock.json is absent; prefer npm ci and a committed lockfile for reproducible frontend builds")

    if errors:
        print("PORTABILITY PREFLIGHT: FAIL")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARNING: {item}")
        return 1

    print("PORTABILITY PREFLIGHT: PASS")
    print(f"Checked {len(REQUIRED_FILES)} required source/configuration paths and tracked-file exclusions.")
    for item in warnings:
        print(f"WARNING: {item}")
    print("This is a repository preflight only; it does not prove runtime functionality or a successful restore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
