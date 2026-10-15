# Medical Archive: target architecture and acceptance criteria

## Goal

Make ingestion deterministic, auditable, tenant-safe, and reviewable. Classification is a subsystem of ingestion, not the source of truth for ownership, identity, dates, or storage.

## Target pipeline

1. **Request / upload boundary**
   - Authenticate user and resolve an authorized family archive.
   - Resolve patient only among patients in that family.
   - Validate extension, MIME/signature where feasible, upload size, and duplicate digest.
   - Keep raw upload immutable; never overwrite an existing original.

2. **Document extraction**
   - Preserve original file and calculate SHA-256.
   - Extract OCR text with page boundaries and OCR diagnostics.
   - Keep OCR text and derived medical metadata encrypted at rest.
   - Every extracted fact should retain source page/line where feasible.

3. **Metadata resolution**
   - Resolve separately: document date, event date, issue date, upload timestamp, registered patient name, document title, file digest.
   - Never substitute upload date for a missing document date.
   - Match the extracted patient only against the current family's configured patient list.
   - Ambiguous/no match means pending review; never silently attach to a different patient.

4. **Classification**
   - Separate document form/type from clinical content tags.
   - Use explainable evidence and deterministic scoring.
   - Return primary type, secondary type candidates, confidence/evidence, classifier version, and review_required.
   - Unknown or conflicting evidence must abstain and enter manual review rather than force a label.
   - Page-level classification is independent; a page with weak evidence must not inherit a different page's type.

5. **Persistence and storage**
   - Persist tenant/family ID on every indexed entity and include it in every query.
   - Store originals and OCR sidecars under validated family/patient paths or the selected per-family cloud backend.
   - Do not store plaintext tokens/OCR/keywords/analysis in the database.
   - A failed database insert must clean up only files created by that same request.
   - Keep a recoverable processing state so interrupted uploads can be resumed or retried idempotently.

6. **Review and retrieval**
   - Show original document next to extracted metadata and evidence.
   - Permit correction of patient, dates, document title/type, and tags with an audit trail.
   - Search across OCR and structured fields with explicit family/patient scope.
   - Mark uncertain extraction distinctly from verified user corrections.

7. **Optional AI analysis**
   - Be independent from classification and archive retrieval.
   - Require explicit consent for sending selected OCR excerpts to a remote inference provider.
   - Minimize excerpts, log provider/model version without logging medical text, and retain clear source references.
   - Present answers as informational and linked to source documents; do not automate diagnosis or treatment.

## Recommended module boundaries

- `ingestion`: validate upload, hash, deduplicate, orchestrate states, cleanup on failure.
- `ocr`: file-to-page-text extraction and quality diagnostics.
- `AIAnalise` (later rename to `classification`): pure, testable classifier and structured extraction.
- `document_metadata`: patient/date/title/name resolution with explicit confidence and evidence.
- `database`: persistence/query boundary; enforce family scope centrally.
- `local_storage` / cloud adapter: path-safe immutable originals and OCR sidecars.
- `tenancy`: family membership, roles, encrypted secrets and access checks.
- `webapp` / Telegram adapters: thin interfaces calling shared application services.
- `review`: pending queue, user corrections, audit events.
- `ai_analysis`: opt-in external LLM query assembly and source-grounded answer generation.

Do not perform a large mechanical refactor in one patch. Extract one boundary at a time, keep old public interfaces during migration, and add contract tests before switching callers.

## Release gates

### Functional
- Unit tests for every document type and known adversarial/conflicting case.
- Deterministic corpus evaluator; per-class precision/recall/F1 and abstention/review rate.
- Patient/date/title matching tests for aliases, OCR typos, ambiguous names, multiple dates, missing dates, and family collisions.
- Upload integration tests for duplicate, malformed, oversized, interrupted and retry scenarios.
- Contract tests proving Telegram and web use the same ingestion/classification/metadata services.

### Security and privacy
- Tenant-isolation tests for every read/write/download/search path.
- Path traversal and overwrite protection tests.
- Encryption-at-rest checks for OCR, keywords, structured analysis and OAuth tokens.
- No secrets or patient text in logs, CI output, fixtures, screenshots or public corpus probes.
- External AI tests verify that no content is sent before explicit consent.

### Reliability
- Idempotent retries and consistent cleanup on partial failure.
- Schema migrations are explicit, backed up, and reversible where practical.
- Backup/restore test before enabling real medical records.
- Health checks and observable processing errors without leaking medical data.

### Acceptance conditions
- All automated tests pass on Python 3.11 in CI.
- Classifier metrics are reported honestly on a reviewed, permissioned evaluation set; synthetic fixtures are labelled as synthetic.
- End-to-end upload → OCR → metadata → review → persistence → retrieval has passed using synthetic files.
- Live OAuth and remote AI paths are tested only with dedicated test credentials and no real patient records.
- No production deployment or merge based solely on curated test accuracy.

## Work sequence

1. Establish CI and a single canonical test command.
2. Consolidate current metadata resolver and test its date/patient ambiguity cases.
3. Extract shared ingestion orchestration from web/Telegram routes.
4. Add a persisted pending-review workflow for ambiguous patient/type/date cases.
5. Add audit-friendly user corrections and source provenance.
6. Harden retries, cleanup, backups and restore.
7. Add independent, permissioned real-world evaluation before tuning classifier rules.
8. Perform security review and synthetic end-to-end rollout rehearsal.

## Current status note

This document specifies the target architecture and release gates; it does not claim that all items are implemented. Verify branch provenance and test results before considering the project production-ready.
