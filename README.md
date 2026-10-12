# Medical Archive

Family medical-document archive with a Telegram bot and an experimental web interface. Each family is a separate tenant, with family-scoped document index and isolated document storage.

## Features

- Telegram interface (requires access to Telegram Bot API from the server).
- Experimental web interface at / using HTTP Basic authentication.
- Family spaces, patient lists, family-scoped search/history.
- Upload PDF and common image formats; OCR with Tesseract (Russian + English).
- Local document storage on the VPS by default; optional Yandex Disk backend.
- Multi-label content classification for mixed documents, with page-level type signals.
- OCR-indexed lab markers, diagnosis/medication snippets and structured-data search.
- Optional Hugging Face question answering over selected archive snippets.
- OCR text, keywords, structured analysis and Yandex OAuth tokens encrypted in SQLite using Fernet.
- Docker Compose deployment and tenant-isolation tests.

## Web MVP setup

1. Copy .env.example to .env; set FERNET_KEY, WEB_USERNAME, and a long unique WEB_PASSWORD.
2. For local-only document storage, keep `DOCUMENT_STORAGE_BACKEND=local` (default). Originals and OCR sidecar files are saved under `./data/documents/family_<id>/<patient>/` on the host, persisted through the Docker data volume.
3. Optionally, set up Yandex OAuth and use `DOCUMENT_STORAGE_BACKEND=yandex` when the integration is available. Register the callback exactly as `https://YOUR-DOMAIN.example/oauth/yandex/callback`.
4. Expose the web interface only behind HTTPS with Nginx. Compose binds application ports to localhost.
5. Run `docker compose up -d --build`.
6. Open the HTTPS endpoint and sign in with the configured HTTP Basic account. Create a family, add a patient, then test using a small synthetic PDF/image.
7. The patient page allows uploads, OCR, full-text/structured search and opening the original file. Mixed files can carry multiple content labels; extracted facts retain page/source-line information for manual verification.

The web interface runs separately from the Telegram bot but uses the same SQLite database and shared code. The web login is a single configured test owner; this MVP does not yet support individual web accounts or inviting web users. Web-created family membership uses a negative numeric ID namespace to avoid collisions with Telegram IDs.

## Security and limitations

- **Test MVP only. Do not upload real medical records yet.**
- The initial multi-label analyzer uses explainable text patterns and OCR line extraction, not a clinically validated classifier. Extracted values are candidates linked to source lines/pages and must be checked against the original; no diagnosis or treatment decision is automated.
- Expose the web interface only behind HTTPS. Application ports must remain bound to localhost; HTTP Basic is not safe over plain HTTP.
- Local documents are kept on the VPS, not encrypted as individual files. Files use restrictive directory/file permissions, and OCR text/keywords in SQLite are Fernet-encrypted. Protect the VPS and back up the data volume securely.
- Configure encrypted off-server backups and securely back up FERNET_KEY. If it is lost, encrypted data cannot be recovered.
- Web and Telegram share the database file and local storage volume on one host. Do not run independent copies against separate databases expecting automatic sync.
- AI sends selected OCR excerpts to Hugging Face and its selected inference provider after explicit consent. Output can be wrong and is not a diagnosis.
- This is not a clinically validated product. Before real records, add per-user web accounts, CSRF protection where applicable, rate limits, stronger audit logging, backup/restore testing and comprehensive isolation tests.
- The starter VPS has about 1 GB RAM and one vCPU; concurrent OCR may exhaust memory. Keep test PDFs small and process one upload at a time.

## Development checks

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

See DEPLOYMENT.md for rollout and security checks.
