# VPS deployment and multi-family architecture

## Target deployment

- Ubuntu 24.04 LTS
- 2 vCPU, 4 GB RAM, 50–60 GB SSD/NVMe
- Python bot + Tesseract OCR (Russian and English) + SQLite
- Original files stored on each family's own Yandex Disk
- Hosted LLM through Hugging Face Inference Providers; no local model/GPU

## Budget notes

The VPS budget covers only the application server. Hugging Face inference is billed separately after the account's monthly included credits are exhausted. Confirm that payment is available to the account before relying on paid inference.

## Multi-family isolation requirements

- Each family is a tenant with its own family ID.
- Patients, documents, search results, history exports and AI context must always be scoped to the active family.
- Telegram IDs are members of explicit families with roles (owner/admin/member).
- Each family authorizes its own Yandex Disk through OAuth. Do not ask users to send account passwords.
- Store OAuth tokens encrypted at rest using Fernet and a secret key kept only in the server environment.
- Never expose tokens, OCR text, medical names or document contents in application logs.
- AI prompts should include only the minimum excerpts needed to answer; avoid sending Telegram IDs and unnecessary personal identifiers to the model provider.
- Do not deploy with real medical records until tenant-isolation tests pass.

## Initial release checklist

1. Configure a Telegram bot and Hugging Face token.
2. Register a Yandex OAuth application and configure its callback URL.
3. Set a strong FERNET_KEY, keep .env out of Git, and restrict Telegram access.
4. Test uploads, OCR, search, history, and AI against synthetic documents.
5. Test that a member of one family cannot access another family's patient names, files, history, or AI context.
6. Configure encrypted backups and test restoration before using real records.
