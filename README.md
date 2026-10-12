# Medical Archive

Family medical-document archive with a Telegram bot and an experimental web interface. Each family is a separate tenant, with its own Yandex Disk OAuth connection and family-scoped document index.

## Features

- Telegram interface (requires access to Telegram Bot API from the server).
- Experimental web interface at / using HTTP Basic authentication.
- Family spaces, patient lists, family-scoped search/history.
- Upload PDF and common image formats; OCR with Tesseract (Russian + English).
- Originals and OCR text files stored on the family's Yandex Disk.
- Optional Hugging Face analysis.
- OCR text, keywords and Yandex OAuth tokens encrypted in SQLite using Fernet.
- Docker Compose deployment and tenant-isolation tests.

## Web MVP setup

1. Copy .env.example to .env; set FERNET_KEY, WEB_USERNAME, and a long unique WEB_PASSWORD.
2. Set Yandex OAuth values. Register the callback exactly as https://YOUR-DOMAIN.example/oauth/yandex/callback.
3. Set up a domain, HTTPS certificate and Nginx using nginx/medical-archive.conf.example.
4. Run docker compose up -d --build.
5. Open https://YOUR-DOMAIN.example/. The browser asks for the configured HTTP Basic username and password.
6. Create a family, connect its Yandex Disk, add a patient, then test with a synthetic document.

The web interface runs separately from the Telegram bot but uses the same SQLite database and shared code. The web login is a single configured test owner; this MVP does not yet support individual web accounts or inviting web users. Web-created family membership uses a negative numeric ID namespace to avoid collisions with Telegram IDs.

## Telegram quick start

1. Set BOT_TOKEN in .env.
2. Start the service and open the bot.
3. Run /newfamily Family Name, then /connect_disk.
4. Invite relatives with /invite TELEGRAM_ID member.

## Security and limitations

- **Test MVP only. Do not upload real medical records yet.**
- Expose the web interface only behind HTTPS. The application ports are bound to localhost by Compose.
- HTTP Basic sends credentials on every request; never use over plain HTTP.
- Configure encrypted off-server backups and securely back up FERNET_KEY. If it is lost, encrypted data cannot be recovered.
- Web and Telegram share the database file on one host. Do not run independent copies against separate databases expecting automatic sync.
- AI sends selected OCR excerpts to Hugging Face and its selected inference provider after explicit consent. Output can be wrong and is not a diagnosis.
- This is not a clinically validated product. Before real records, add per-user web accounts, CSRF protection where applicable, rate limits, stronger audit logging, backup/restore testing and comprehensive isolation tests.
- The starter VPS has about 1 GB RAM and one vCPU; concurrent OCR may exhaust memory. Keep test PDFs small and process one upload at a time.

## Development checks

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

See DEPLOYMENT.md for rollout and security checks.