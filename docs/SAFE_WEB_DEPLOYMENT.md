# Безопасное обновление веб-архива

## Почему test/test может не работать

На VPS нельзя делать `git pull` или переключать основную рабочую директорию, если в ней есть незакоммиченные изменения. Веб-контейнер может продолжать работать на старом Docker-образе даже после обновления GitHub.

## Релизный процесс

1. Слить и проверить PR в `release/web-2026-10`.
2. Убедиться, что CI завершился успешно.
3. На VPS безопасно извлечь deploy-скрипт из удалённой релизной ветки во временный файл — это не меняет текущую рабочую директорию с незакоммиченными изменениями:

   ```bash
   git -c safe.directory=/opt/medical-assistant-bot -C /opt/medical-assistant-bot fetch origin release/web-2026-10
   git -c safe.directory=/opt/medical-assistant-bot -C /opt/medical-assistant-bot show origin/release/web-2026-10:scripts/deploy_web_release.sh > /tmp/deploy_web_release.sh
   chmod 700 /tmp/deploy_web_release.sh
   sudo env SOURCE_ROOT=/opt/medical-assistant-bot bash /tmp/deploy_web_release.sh
   ```

4. Скрипт создаёт отдельный Git worktree `/opt/medical-archive-release`, ссылается на существующие `.env` и `data` без копирования/перезаписи и обновляет только `medical-archive-web`.
5. Перед обновлением создаётся отдельная SQLite backup-копия в `/opt/medical-archive-backups` с ограниченными правами.
6. После запуска smoke-тест проверяет вход демо-пользователя, secure cookie, React bundle, PWA manifest и PNG-иконку. Пароль не выводится, внешний ИИ не вызывается.
7. Если smoke-тест не проходит, скрипт пытается вернуть предыдущий образ веб-контейнера.

## Что скрипт намеренно не делает

- Не переключает и не сбрасывает исходную рабочую директорию.
- Не выполняет `git stash`, `git reset` или `git clean`.
- Не меняет `.env`, ключи, файлы данных и SQLite-схему вручную.
- Не перезапускает Telegram-бот или другие сервисы.
- Не делает публичный HTTP-запрос с паролем: smoke-тест обращается к `127.0.0.1:8000`.

Перед запуском требуется проверить, что текущий путь `/opt/medical-assistant-bot` содержит актуальные `.env` и `data/archive.sqlite3`. Скрипт откажется продолжать, если путь назначения занят не-Git-каталогом, worktree содержит tracked-изменения или БД не найдена.
