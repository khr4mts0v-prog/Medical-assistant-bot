# Deployment guide

Target: Ubuntu 24.04, Docker Compose, Nginx + HTTPS. The current low-cost test VPS has about 1 GB RAM and one vCPU; use small synthetic documents and avoid concurrent OCR.

## Configure

1. Keep .env mode 600. Set FERNET_KEY, WEB_USERNAME and a long unique WEB_PASSWORD. Never commit .env.
2. During the current private MVP testing phase, demo login defaults to `test/test`. Keep the endpoint restricted to HTTPS and trusted testers; before any public launch, set unique `DEMO_USERNAME` and `DEMO_PASSWORD` values in `.env`.
2. Set `DOCUMENT_STORAGE_BACKEND=local` to store web uploads on the VPS. This is the default.
3. The web service and Telegram bot share `./data:/app/data`. Local originals and OCR sidecars are stored at `./data/documents/family_<id>/<patient>/`; SQLite remains `./data/archive.sqlite3`.
4. Run `docker compose config --quiet` and `docker compose up -d --build`.
5. Check `docker compose ps -a`, `docker compose logs --tail=100 medical-archive-web`, and `curl -I http://127.0.0.1:8000/` (should return 401 with HTTP Basic enabled).
6. Open the HTTPS endpoint, sign in, create/select a family, add a patient, and test a small synthetic PDF/image. Check that the original can be opened from the document list.
7. Optional Yandex Disk: configure OAuth secrets and set `DOCUMENT_STORAGE_BACKEND=yandex`. Its callback must match the registered HTTPS URI exactly.

## Data and security

- Keep port 8000 bound to 127.0.0.1; do not expose it directly to the internet. Use HTTPS via Nginx.
- Back up `data/` and FERNET_KEY securely; test restoration. Keep the encryption key separate from database backups.
- Local documents are not encrypted individually at rest. Files are stored with restrictive permissions on the host; restrict VPS and administrator access and use encrypted backups.
- Never upload real medical records to this test MVP. It lacks per-person web accounts, rate limiting, a full security review, and comprehensive integration tests.
- The web login currently represents one configured web owner account. Family memberships are stored in the existing family_members table using a negative numeric principal ID, separate from positive Telegram IDs.
- AI analysis sends selected OCR text to Hugging Face after consent. Verify provider billing and privacy terms before enabling.

## Tests

Run `python -m compileall -q .` and `python -m unittest discover -s tests -v`. Test family isolation, login failures, local upload/download, backups and restoration before considering production use.
