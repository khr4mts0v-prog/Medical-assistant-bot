# Medical Archive Bot

Telegram bot for family medical-document archives. Each family is a separate tenant, with its own Yandex Disk OAuth connection and family-scoped document index.

## Current MVP features

- Family spaces and Telegram membership roles.
- Per-family Yandex Disk OAuth connection.
- Upload of PDF and common image formats.
- OCR with Tesseract (Russian + English).
- Family-scoped patient list, search and history.
- Optional Hugging Face Inference Providers analysis with per-family consent.
- Encryption of OCR text, keywords and Yandex OAuth tokens in SQLite.
- Docker Compose deployment and tenant-isolation unit tests.

## Important

This is an MVP under active development, not a clinically validated product. Do not upload real medical documents until you have configured secrets, HTTPS/OAuth, backups and reviewed the test results. AI sends selected document excerpts to Hugging Face and the selected inference provider after the user consents; model output can be wrong and is not a medical diagnosis.

## Quick start

1. Copy `.env.example` to `.env`.
2. Set `BOT_TOKEN`, generate `FERNET_KEY`, configure Yandex OAuth credentials and HTTPS callback. `HF_API_TOKEN` is optional for OCR/search but required for AI analysis.
3. On VPS, follow [DEPLOYMENT.md](DEPLOYMENT.md). Tesseract language packs and Python dependencies are included in the Docker image.
4. Start the bot and run `/newfamily Family Name`.
5. Run `/connect_disk` and authorize the Yandex account belonging to that family.
6. Invite family members with `/invite TELEGRAM_ID member`. They can retrieve their ID with `/id`.
7. Use `/families` to switch between archives.

## Commands

- `/start` — start the bot
- `/id` — show your Telegram numeric ID
- `/newfamily Name` — create a family archive
- `/families` — switch family
- `/invite ID [member|admin]` — invite a Telegram account
- `/connect_disk` — connect the active family's Yandex Disk
- `/help` — usage

## Development checks

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for HTTPS reverse proxy, security and rollout requirements.
