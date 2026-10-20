# Deployment guide

Target: Ubuntu 24.04, Docker Compose, Nginx + HTTPS. The current low-cost test VPS has about 1 GB RAM and one vCPU; use small synthetic documents and avoid concurrent OCR.

## Configure

1. Keep .env mode 600. Set FERNET_KEY, WEB_USERNAME and a long unique WEB_PASSWORD. Set `WEB_SESSION_SECRET` to a random value of at least 32 characters (generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Never commit .env.
2. During the current private MVP testing phase, demo login defaults to `test/test`. Keep the endpoint restricted to HTTPS and trusted testers; before any public launch, set unique `DEMO_USERNAME` and `DEMO_PASSWORD` values in `.env`.
2. Set `DOCUMENT_STORAGE_BACKEND=local` to store web uploads on the VPS. This is the default.
3. The web service and Telegram bot share `./data:/app/data`. Local originals and OCR sidecars are stored at `./data/documents/family_<id>/<patient>/`; SQLite remains `./data/archive.sqlite3`.
4. Run `docker compose config --quiet` and `docker compose up -d --build`.
5. Check `docker compose ps -a`, `docker compose logs --tail=100 medical-archive-web`, and `curl -I http://127.0.0.1:8000/`. An unauthenticated request should be rejected without a browser HTTP Basic challenge; the PWA should direct the user to `/login`.
6. Open the HTTPS endpoint, sign in, create/select a family, add a patient, and test a small synthetic PDF/image. Check that the original can be opened from the document list.
7. Optional Yandex Disk: configure OAuth secrets and set `DOCUMENT_STORAGE_BACKEND=yandex`. Its callback must match the registered HTTPS URI exactly.

## Production release gate

Before a release that may contain real medical data, run `python3 scripts/check_production_env.py --env-file /path/to/.env`. The deploy script runs this check before backup/build/restart and fails closed; it never creates or edits secrets in `.env`.

The preflight requires:
- a unique web password of at least 20 characters, a session signing secret of at least 32 characters, and a valid `FERNET_KEY`;
- demo login to be explicitly disabled with both demo variables empty, or configured with non-default unique credentials;
- `.env` permissions that deny all group/other access;
- when local storage is selected, explicit confirmation that the underlying volume and backups are encrypted at rest.

`LOCAL_STORAGE_AT_REST_PROTECTED=true` is an operator attestation, not an automatic encryption mechanism. Set it only after verifying the actual VPS/provider storage and backup protections. If that cannot be verified, the release gate must remain blocked.

## Data and security

- Keep port 8000 bound to 127.0.0.1; do not expose it directly to the internet. Use HTTPS via Nginx.
- Back up `data/` and FERNET_KEY securely; test restoration. Keep the encryption key separate from database backups.
- The database encrypts OCR text, keywords, analysis and pending-file bytes with Fernet. **Local originals and OCR sidecars are plaintext files** with restrictive file permissions; filesystem encryption is still required for production use. Restrict VPS and administrator access and use encrypted backups.
- Do not treat this MVP as publicly production-ready until the full security review and integration-test gates are complete. Web access currently uses a configured owner account rather than per-person web accounts. AI and upload endpoints have process-local rate limits, which must be complemented by reverse-proxy limits and are not a substitute for a full security review.
- The browser login uses a signed, HttpOnly, Secure, SameSite=Lax cookie with a bounded lifetime. Legacy HTTP Basic clients remain supported. The web login still represents the configured web owner account; family memberships are stored in the existing family_members table using a negative numeric principal ID, separate from positive Telegram IDs.
- The assistant uses the configured external provider (`AI_PROVIDER=polza` or `huggingface`). Only send questions and relevant medical fragments after explicit consent; verify the selected provider's retention, privacy, data-processing terms, and billing before enabling it.

## Tests

Run `python -m compileall -q .` and `python -m unittest discover -s tests -v`. Test family isolation, login failures, local upload/download, backups and restoration before considering production use.