# Deployment guide

Target: Ubuntu 24.04, Docker Compose, Nginx + HTTPS. The current low-cost test VPS has only about 1 GB RAM and one vCPU; use small synthetic documents and avoid concurrent OCR.

## Configure

1. Copy .env.example to .env and set FERNET_KEY, WEB_USERNAME, and a long unique WEB_PASSWORD. Keep .env mode 600 and never commit it.
2. Set BOT_TOKEN if the Telegram bot should run on this host. Telegram API reachability is independent of the web interface.
3. Register a Yandex OAuth application with Disk read/write scope and callback exactly `https://YOUR-DOMAIN.example/oauth/yandex/callback`.
4. Point a domain at the VPS. Install Nginx and Certbot, obtain a TLS certificate, then configure nginx/medical-archive.conf.example with the actual domain and certificate paths.
5. Ensure Nginx proxies to 127.0.0.1:8000. Compose binds web and OAuth app ports to localhost only.
6. Run `docker compose config --quiet` and `docker compose up -d --build`.
7. Check `docker compose ps -a`, `docker compose logs --tail=100 medical-archive-web`, and `curl -I http://127.0.0.1:8000/` (the last command should return 401 because HTTP Basic is enabled).
8. Open the HTTPS domain in a browser and sign in with WEB_USERNAME and WEB_PASSWORD. Create a family, connect its Yandex Disk, add a patient, and test with synthetic PDFs/images.

## Telegram

The Telegram container requires the VPS to reach api.telegram.org:443. If that route is blocked, the Telegram container may repeatedly time out while the independent web service can still run. Do not rotate BOT_TOKEN unless Telegram returns an authentication error rather than a network timeout.

## Data and security

- Both services use the same SQLite database file via the `data/` volume on this host.
- Never expose port 8000 directly to the public internet. Keep it bound to 127.0.0.1 and use HTTPS in Nginx; HTTP Basic is not safe over plain HTTP.
- Back up `data/` and FERNET_KEY securely and test restoration. Keep the encryption key separate from database backups.
- Do not upload real medical documents to this test MVP. It lacks per-person web accounts, rate limiting, a full security review, and comprehensive integration tests.
- The web login currently represents one configured web owner account. Web family memberships are stored in the existing family_members table with a negative numeric principal ID, separate from normal positive Telegram IDs.
- AI analysis sends selected OCR text to Hugging Face after consent. Verify provider billing and privacy terms before enabling.

## Tests

Run `python -m compileall -q .` and `python -m unittest discover -s tests -v` in an environment with requirements installed. Test family isolation, login failures, OAuth failure paths, uploads, backups, and restoration before considering production use.