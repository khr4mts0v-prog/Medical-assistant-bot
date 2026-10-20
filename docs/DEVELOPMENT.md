# Development workflow

## Canonical local test run

Use the project's isolated virtual environment when it exists:

```bash
./.venv/bin/python -m pytest -q
```

CI must install declared dependencies and run the same logical suite on Python 3.11. Keep corpus evaluation deterministic and separate from any optional network-based public-dataset probes.

## Branch and pull-request rules

- Work on one focused feature branch per architectural increment.
- Base changes on the actual branch that contains the prerequisite code; do not assume an open PR has been merged.
- Never force-push or reset the VPS checkout to make branches match.
- Before creating a PR, inspect `git status --short`, diff, base/head SHA, and tests.
- Do not include `.env`, database files, medical documents, OCR text, tokens or local test artifacts.
- Keep PRs draft until CI passes and acceptance conditions are reviewed.
- Do not deploy automatically from an open PR.

## Data and security

Use synthetic documents for development. Do not log full OCR text or model prompts. Treat family identifiers as authorization boundaries and include family scope in all database access. Do not automatically map an uncertain document to a patient. Keep originals immutable and make updates to extracted metadata auditable.
