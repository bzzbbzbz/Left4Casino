# Staging / Production Runbook

Безопасный регламент разработки и релизов для Left4Casino.

---

## Цель

- тестировать изменения на отдельном Telegram-боте;
- не смешивать staging и production данные;
- обновлять production только через GitHub flow.

---

## Текущее состояние сервера

На 2026-05-09 фактическая схема такая:

- Production runtime: `/root/n8n-install/python-runner`, Docker container `python-runner`.
- Staging runtime: `/opt/left4casino/python-runner-stage`, systemd service `left4casino-stage.service`.
- Production worktree: `/opt/left4casino/python-runner-prod`, подготовлен для будущего workflow, но не используется как live runtime.

Production не переводится с Docker на systemd без отдельного явного решения. Все инструкции ниже для systemd production являются целевым шаблоном, а не текущим live-путём.

---

## 1. Рекомендуемая структура

```text
/opt/left4casino/
├── python-runner-prod/
└── python-runner-stage/
```

- `python-runner-prod` — стабильная ветка (`master` или `main`) для подготовленного prod worktree;
- `python-runner-stage` — текущая feature-ветка для тестирования.

Для текущего live production используется Docker-копия `/root/n8n-install/python-runner`; её не смешивать со staging worktree.

---

## 2. Создание двух рабочих копий через git worktree

```bash
git fetch origin

git worktree add "/opt/left4casino/python-runner-prod" master
git worktree add -b feature/stage-bootstrap "/opt/left4casino/python-runner-stage" origin/master
```

Если production-ветка называется `main`, замените `master` на `main` во всех командах.

Проверка:

```bash
git worktree list
```

---

## 3. Конфиги и секреты

### Production

```bash
cp settings.example.toml settings.prod.toml
cp env/prod.example.env env/prod.env
chmod 600 settings.prod.toml env/prod.env
```

### Staging

```bash
cp settings.example.toml settings.stage.toml
cp env/stage.example.env env/stage.env
chmod 600 settings.stage.toml env/stage.env
```

Обязательные правила:

- у stage и prod **разные bot tokens**;
- у stage и prod **разные `CASINO_DB_PATH`**;
- у stage и prod **разные `allowed_chat_ids`**;
- файлы `settings.*.toml` и `env/*.env` не коммитятся.

---

## 4. Изоляция данных

Используйте разные SQLite файлы:

- prod: `/opt/left4casino/python-runner-prod/data/casino.prod.db`
- stage: `/opt/left4casino/python-runner-stage/data/casino.stage.db`

Приложение поддерживает переопределение через:

```bash
CASINO_DB_PATH=/absolute/path/to/casino.db
```

Это защищает от случайного подключения staging к боевой БД.

---

## 5. Ограничение staging только тестовыми чатами

В `settings.stage.toml` обязательно задайте:

```toml
[chat_restrictions]
block_private_chats = false
allowed_chat_ids = [-1001234567890]
```

Используйте только тестовые группы. Не включайте сюда production chat IDs.

---

## 6. Запуск через systemd

Для staging используется отдельный unit-файл:

- `left4casino-stage.service`

Для future production worktree подготовлен пример unit-файла, но текущий live production работает через Docker и не должен переводиться на systemd без отдельного решения:

- `left4casino-prod.service`

Примеры находятся в репозитории:

- `left4casino-prod.example.service`
- `left4casino-stage.example.service`

После установки:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now left4casino-stage
```

Проверка:

```bash
systemctl status left4casino-prod --no-pager
systemctl status left4casino-stage --no-pager
```

Для текущего Docker production проверка выполняется через Docker/container logs, а не через `left4casino-prod.service`.

---

## 7. Повседневная разработка

### Создать feature-ветку в stage

```bash
git -C /opt/left4casino/python-runner-stage switch -c feature/my-change
```

### Внести изменения и проверить локально

```bash
cd /opt/left4casino/python-runner-stage
./scripts/lint.sh
./scripts/test.sh
```

### Проверить staging-бота

- бот запускается с `settings.stage.toml`;
- отвечает только в тестовом чате;
- пишет данные только в `casino.stage.db`.

---

## 8. GitHub flow

```bash
git add .
git commit -m "your message"
git push -u origin feature/my-change
```

Дальше:

1. Создать Pull Request в production-ветку.
2. Дождаться зелёных checks:
   - `Lint`
   - `Tests`
3. Выполнить merge.

---

## 9. Backup перед production deploy

Перед каждым обновлением production:

```bash
BACKUP_DIR="/opt/left4casino/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cp "/opt/left4casino/python-runner-prod/settings.prod.toml" "$BACKUP_DIR/"
cp "/opt/left4casino/python-runner-prod/env/prod.env" "$BACKUP_DIR/"
cp "/opt/left4casino/python-runner-prod/data/casino.prod.db" "$BACKUP_DIR/"
```

Если хотите максимально безопасно:

```bash
sudo systemctl stop left4casino-prod
cp "/opt/left4casino/python-runner-prod/data/casino.prod.db" "$BACKUP_DIR/"
sudo systemctl start left4casino-prod
```

---

## 10. Production deploy (current Docker runtime)

Текущий production работает из `/root/n8n-install/python-runner` в Docker-контейнере `python-runner`. Перед обновлением обязательно сделать backup БД и локальных конфигов.

Минимальная схема:

```bash
cd /root/n8n-install/python-runner
git fetch origin
git pull --ff-only origin master
./scripts/lint.sh
./scripts/test.sh
docker restart python-runner
```

Проверка после деплоя:

```bash
docker ps --filter name=python-runner
docker logs python-runner --since 10m
```

Если production-ветка называется `main`, используйте `origin/main`.

---

## 11. Production deploy (future systemd worktree template)

```bash
cd /opt/left4casino/python-runner-prod
git fetch origin
git reset --hard origin/master
./scripts/lint.sh
./scripts/test.sh
sudo systemctl restart left4casino-prod
```

Этот путь не является текущим live production, пока явно не принято решение о переводе production с Docker на systemd. Если production-ветка называется `main`, используйте `origin/main`.

Проверка после деплоя:

```bash
systemctl status left4casino-prod --no-pager
journalctl -u left4casino-prod -n 100 --no-pager
```

---

## 12. Rollback

### Вариант A: откат к предыдущему коммиту

```bash
cd /opt/left4casino/python-runner-prod
git log --oneline -n 5
git reset --hard <previous_commit>
sudo systemctl restart left4casino-prod
```

### Вариант B: откат БД из backup

```bash
sudo systemctl stop left4casino-prod
cp "/opt/left4casino/backups/YYYYMMDD_HHMMSS/casino.prod.db" \
   "/opt/left4casino/python-runner-prod/data/casino.prod.db"
sudo systemctl start left4casino-prod
```

---

## 13. Чеклист безопасности

- [ ] Не использовать production token в stage
- [ ] Не использовать одну и ту же SQLite БД в stage и prod
- [ ] Не коммитить `settings.*.toml`, `env/*.env`, `*.db`
- [ ] Не тестировать stage в боевых чатах
- [ ] Не деплоить в production без backup
- [ ] Не мержить PR без зелёных `Lint` и `Tests`
- [ ] Не переводить live production с Docker на systemd без отдельного решения

---

## 14. Минимальный smoke-check после релиза

- [ ] сервис `left4casino-prod` в статусе `active (running)`;
- [ ] бот отвечает на `/start` или `/balance` в production-чате;
- [ ] в логах нет traceback;
- [ ] stage-бот продолжает работать отдельно;
- [ ] production БД не изменилась путём/именем на stage-файл.
