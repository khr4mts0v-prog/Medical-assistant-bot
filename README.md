# Medical Archive

Family medical-document archive with a web interface and optional Telegram bot. Each family is a separate tenant, with family-scoped document index and isolated document storage.

## Web MVP

- Upload PDF and common image formats; OCR with Tesseract (Russian + English).
- Local document storage on the VPS by default; optional Yandex Disk backend.
- Rule-based, explainable multi-label classification, separately tracking document form and clinical content tags.
- Page-level type signals for mixed multi-page files.
- OCR-indexed lab markers, diagnosis/medication snippets and structured-data search.
- Optional Hugging Face question answering over selected archive snippets, independent from classification.
- OCR text, keywords, structured analysis and Yandex OAuth tokens encrypted in SQLite using Fernet.

## Classification design and limitations

The classifier does not call an external AI. It scores explicit document-title/form evidence more highly than incidental mentions, separates document types (e.g. discharge summary, laboratory report, ultrasound conclusion, prescription) from content tags (e.g. diagnoses, medications, vaccination, pregnancy), and stores page-level evidence. When evidence is weak, it returns "не определено" and marks the document for manual review instead of forcing a label.

This is a rule-based MVP, not a clinically validated classifier. Synthetic unit tests protect known patterns and known failure cases, but do not establish real-world accuracy. To estimate quality, create a de-identified representative evaluation set of actual document types and OCR conditions, adjudicate gold labels, report per-class precision/recall/F1 and the unknown/manual-review rate, and inspect errors before tuning rules. Never claim perfect classification from unit tests alone. Mixed PDFs and poor OCR should remain reviewable. Extracted values are candidates linked to source lines/pages and must be checked against the original; no diagnosis or treatment decision is automated.

## Security

- Test MVP only. Do not upload real medical records yet.
- Expose the web interface only behind HTTPS. Application ports must remain bound to localhost; HTTP Basic is not safe over plain HTTP.
- Local documents are kept on the VPS, not encrypted as individual files. OCR text, keywords and structured analysis in SQLite are Fernet-encrypted. Protect the VPS and back up the data volume securely.
- Configure encrypted off-server backups and securely back up FERNET_KEY. If it is lost, encrypted data cannot be recovered.
- Before real records, review user access controls, CSRF protection where applicable, rate limits, audit logging, backup/restore and tenant isolation.
- The starter VPS has about 1 GB RAM and one vCPU; concurrent OCR may exhaust memory. Keep test PDFs small and process one upload at a time.

## Development checks

    python -m compileall -q .
    python -m unittest discover -s tests -v

See DEPLOYMENT.md for rollout and security checks.
