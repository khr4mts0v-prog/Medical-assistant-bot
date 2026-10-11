# VPS deployment and multi-family architecture

## Target deployment

- Ubuntu 24.04 LTS
- 2 vCPU, 4 GB RAM, 50–60 GB SSD/NVMe
- Docker Compose; Python bot + Tesseract OCR (Russian and English) + SQLite
- Original documents on each family's own Yandex Disk
- Hosted LLM through Hugging Face Inference Providers; no local model/GPU
- Nginx + HTTPS for Yandex OAuth callback

## Important cost and privacy notes

The VPS budget covers only the application server. Hugging Face inference is billed separately after included credits are exhausted. Free accounts receive $0.10/month in credits according to current HF documentation; verify payment availability for your country/account before relying on paid inference.

Before each family first uses AI analysis, the bot asks for explicit consent because relevant OCR excerpts are sent to Hugging Face and the selected inference provider. Do not use AI analysis if the family does not agree to that external processing.

OCR text and keywords, plus per-family Yandex OAuth tokens, are encrypted at rest in SQLite using FERNET_KEY. The key must be backed up securely and must not be committed to Git. If the key is lost, encrypted text/tokens cannot be recovered from the database. The VPS still processes plaintext in memory and the chosen AI provider receives selected excerpts.

## Multi-family isolation

- Each family is a tenant with its own family ID.
- Patient lists, document search, history and AI context are scoped by family ID.
- Telegram IDs are members of explicit families with roles (owner/admin/member).
- Each family authorizes its own Yandex Disk through OAuth; never ask for account passwords.
- Tokens are encrypted in SQLite; logs should never contain tokens or OCR text.
- Previous single-family tables are preserved as legacy tables if detected. They are not automatically assigned to a family, because ownership cannot safely be inferred.

## Deployment outline

1. Point a domain/subdomain at the VPS.
2. Install Docker Engine, Docker Compose plugin, Nginx and Certbot.
3. Copy `.env.example` to `.env` and fill in BOT_TOKEN, FERNET_KEY, Yandex OAuth credentials, HTTPS redirect URL and (if available) HF_API_TOKEN.
4. Register an application in Yandex OAuth. Enable Disk read/write access and set the callback URL to exactly `https://YOUR-DOMAIN.example/oauth/yandex/callback`.
5. Configure Nginx from `nginx/medical-archive.conf.example`, replace the example domain and TLS certificate paths, then obtain a certificate with Certbot.
6. Ensure `YANDEX_REDIRECT_URI` exactly matches the registered callback URL. The app inside Docker listens on port 8080; Compose only exposes it on localhost.
7. Run `docker compose up -d --build`; inspect `docker compose logs -f` for startup errors.
8. Open the Telegram bot, run `/newfamily My Family`, then `/connect_disk`. Authorize the correct Yandex account in the browser.
9. Invite relatives with `/invite TELEGRAM_ID member`. They can get their ID with `/id`. Use `/families` to switch archives.
10. Test uploads, OCR, search, history, and AI using synthetic documents first.

## Validation checklist before real records

- Run `python -m unittest discover -s tests -v` (or inspect the GitHub Actions result).
- Confirm one family's member cannot select/search the other family's patients or see its history/AI context.
- Confirm Yandex tokens and OCR text are encrypted in SQLite.
- Test OAuth success, cancellation, expired state, and wrong redirect URI.
- Test large PDFs and multiple users; this initial version processes one file per message and does not combine Telegram albums into a single document.
- Configure encrypted off-server backups and test restoration. Back up the FERNET_KEY separately and securely.
- Review legal/privacy obligations for medical data and the countries where family members and providers are located.
