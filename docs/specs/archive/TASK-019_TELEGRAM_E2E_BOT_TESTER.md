# TASK-019: Telegram bot-to-bot E2E tester

**ID**: TASK-019  
**Title**: Автоматический E2E smoke-тестер для stage/prod-ботов через bot-to-bot Telegram  
**Priority**: MEDIUM  
**Status**: READY_TO_MERGE  
**Created**: 2026-05-09  
**Assignee**: cursor-agent

---

## Контекст

Telegram добавил возможность bot-to-bot communication: боты могут получать сообщения от других ботов в группах и приватных чатах при включённом режиме в BotFather и соблюдении условий доставки сообщений.

Это позволяет сделать отдельного тестового бота, который будет автоматически проверять staging-бота в отдельном Telegram-чате по заранее заданным сценариям. Цель — уменьшить ручные smoke-проверки в Telegram после релизов и инфраструктурных изменений.

Дополнение 2026-05-12: тот же tester-бот должен уметь запускать safe smoke против production-бота в общем test-чате, где находятся stage-бот и prod-бот. Это нужно для быстрой проверки после production rollout без mutating economy сценариев и без прямого доступа к prod DB.

---

## Requirements

### REQ-019-1: Отдельный E2E test bot

Создать отдельного Telegram-бота для live smoke-проверок staging-окружения.

**Acceptance Criteria:**
- Используется отдельный токен, не совпадающий со stage/prod токенами.
- Тестер работает только в staging-чате.
- Тестер не имеет доступа к production-чату и production-БД.
- Bot-to-Bot Communication Mode включён для tester-бота и staging-бота через BotFather.

### REQ-019-2: Сценарии smoke-проверок

Тестер выполняет набор сценариев против staging-бота.

**Acceptance Criteria:**
- Поддержаны базовые команды: `/start`, `/balance`, `/bid`, `/safe`, `/top`, `/stats`.
- Команды отправляются с явным username staging-бота, например `/balance@Left4CasinoStageBot`.
- Поддержана отправка dice-сообщений для слотов через `sendDice(..., emoji="🎰")`.
- Тестер ожидает ответы staging-бота с timeout и валидирует ожидаемые фрагменты текста.
- Результат сценария фиксируется в структурированном отчёте.

### REQ-019-3: Проверка состояния БД после сценариев

Smoke-тест должен проверять не только текстовые ответы, но и фактическое состояние stage SQLite.

**Acceptance Criteria:**
- Проверяется, что тестовый user_id создан в stage-БД.
- Проверяется изменение `balance` после игровых действий.
- Проверяется появление записей в `event_history`.
- Проверяется, что путь БД соответствует stage, а не production.

### REQ-019-4: Защита от bot-to-bot loops

Тестер и staging-бот не должны создавать бесконечные циклы сообщений.

**Acceptance Criteria:**
- У каждого сценария есть максимальное число шагов.
- У каждого ожидания ответа есть timeout.
- Повторяющиеся сообщения дедуплицируются.
- Есть rate limit между действиями тестера.
- Тестер игнорирует сообщения, не относящиеся к активному сценарию.

### REQ-019-5: Интеграция с existing QA flow

Bot-to-bot smoke не заменяет unit/integration тесты, а дополняет их.

**Acceptance Criteria:**
- Основная бизнес-логика остаётся покрытой `./scripts/test.sh`.
- Bot-to-bot тест запускается отдельной командой только против staging.
- CI не требует реального Telegram-токена по умолчанию.
- Live smoke можно запускать вручную перед merge/deploy или по расписанию на stage.

### REQ-019-6: Safe production smoke в test-чате

Тестер выполняет безопасный smoke против production-бота в том же test-чате, где расположен stage-бот.

**Acceptance Criteria:**
- Сценарий запускается как `TELEGRAM_E2E_SCENARIO=prod-smoke`.
- Production bot адресуется явно через `TELEGRAM_E2E_PROD_BOT_USERNAME`, например `/balance@Left4CasinoBot`.
- Сценарий проверяет только `/balance`, `/safe`, `/stats`, `/top`, `/help`.
- Сценарий не запускает slots, `/bid`, `/credit`, event hooks и не читает prod SQLite напрямую.
- Сценарий допускает штатные activity/user row updates от самого prod-бота и не позиционируется как zero-write DB probe.
- `TELEGRAM_E2E_ALLOW_DB_MUTATION=1` и `TELEGRAM_E2E_ALLOW_EVENT_HOOKS=1` для `prod-smoke` запрещены.
- Если задан `TELEGRAM_E2E_PROD_BOT_TOKEN`, проверяется Bot API command menu production-бота без вывода токена и с проверкой, что токен принадлежит `TELEGRAM_E2E_PROD_BOT_USERNAME`.

---

## Goals

**Primary Goal:**  
Сократить ручные Telegram-проверки staging-бота за счёт автоматического live smoke-тестера, который взаимодействует с ботом как внешний Telegram-участник.

**Why This Matters:**
- Проверяет реальную связку Telegram API → aiogram → handlers → SQLite.
- Быстро выявляет проблемы, которые не видны в чистых pytest-тестах: токены, privacy mode, chat restrictions, scheduler/runtime-конфиг.
- Уменьшает риск выката неработающего staging/prod после инфраструктурных изменений.

---

## Design

### Архитектура

```text
staging Telegram group
├── @Left4CasinoStageBot      # тестируемый бот
├── @Left4CasinoBot           # production-бот для safe prod-smoke
└── @Left4CasinoE2ETestBot    # бот-тестер

scripts/telegram_e2e_smoke.py
├── читает env/config stage
├── отправляет команды и dice в staging chat
├── ждёт ответы stage-бота
├── для prod-smoke ждёт ответы prod-бота
├── валидирует текстовые ожидания
├── проверяет stage SQLite
└── выводит итоговый отчёт
```

### Условия Telegram-доставки

Для команд использовать явное обращение к staging-боту:

```text
/balance@Left4CasinoStageBot
```

Для dice-сообщений `🎰` явного mention нет, поэтому staging-бот должен получать bot-to-bot сообщения одним из способов:

- staging-бот является admin в staging-группе;
- или у staging-бота отключён Group Privacy Mode;
- и включён Bot-to-Bot Communication Mode.

### Ограничение по inline-кнопкам

Bot API не позволяет обычному боту нажимать inline callback-кнопки как пользователь. Поэтому flows с кнопками проверяются отдельно:

- callback handlers покрываются pytest integration-тестами;
- live smoke покрывает только те действия, которые tester-бот может выполнить через Bot API;
- при необходимости можно добавить test-only команды, доступные только в stage.

---

## MVP Checklist

- [ ] Создать отдельного Telegram tester-бота через BotFather.
- [ ] Включить Bot-to-Bot Communication Mode для tester-бота и stage-бота.
- [ ] Добавить tester-бота в staging-группу.
- [ ] Проверить privacy/admin настройки, чтобы stage-бот видел dice от tester-бота.
- [ ] Добавить env-переменные для smoke runner: tester token, stage bot username, stage chat id, stage db path.
- [ ] Реализовать `scripts/telegram_e2e_smoke.py`.
- [ ] Добавить сценарий basic smoke: `/start`, `/balance`, `/bid`, `/safe`, `🎰`, `/top`.
- [ ] Добавить проверки stage SQLite после сценария.
- [ ] Добавить loop prevention: timeout, max steps, rate limit, dedupe.
- [ ] Документировать запуск в staging/prod runbook.

---

## Testing & Validation

### Automated

- Unit-тесты парсинга сценариев.
- Unit-тесты дедупликации сообщений.
- Unit-тесты проверки expected text fragments.
- Integration-тесты SQLite assertions на временной БД.

### Live Staging

```bash
python scripts/telegram_e2e_smoke.py --scenario smoke --env stage
```

Additional opt-in scenarios added after staging feedback:

```bash
# Strict parity: /start must not expose old fork casino welcome text or reply keyboard.
TELEGRAM_E2E_SCENARIO=stage-parity python scripts/telegram_e2e_smoke.py

# Economy checks: /bid all-in, /safe deposit/withdraw, /credit entry, spin-until-win.
# DB mutation is explicit and still constrained by the stage DB prefix guard.
TELEGRAM_E2E_SCENARIO=economy \
TELEGRAM_E2E_ALLOW_DB_MUTATION=1 \
TELEGRAM_E2E_MAX_SPINS_UNTIL_WIN=20 \
python scripts/telegram_e2e_smoke.py

# Read-only scheduler readiness report for happy moment/heist scheduled_events rows.
TELEGRAM_E2E_SCENARIO=schedule-readiness python scripts/telegram_e2e_smoke.py

# Strict scheduler readiness: fail unless happy_moment_start and heist_start rows exist.
TELEGRAM_E2E_SCENARIO=schedule-readiness \
TELEGRAM_E2E_SCHEDULE_STRICT=1 \
python scripts/telegram_e2e_smoke.py

# Safe production bot smoke in the shared test chat.
# Requires the same protected E2E env as stage scenarios: tester token, stage settings/db path and target chat.
TELEGRAM_E2E_SCENARIO=prod-smoke \
TELEGRAM_E2E_PROD_BOT_USERNAME=Left4CasinoBot \
TELEGRAM_E2E_TARGET_CHAT_ID=-1003497462507 \
.venv/bin/python scripts/telegram_e2e_smoke.py
```

`TELEGRAM_E2E_STAGE_BOT_TOKEN` is optional and never logged; when present it is used only
to call `getMyCommands` for the stage bot command-menu validation. The tester token cannot
query another bot's command menu, so this check is skipped unless the stage token is supplied.
The runner does not force happy moment/heist schedules automatically; forcing schedules requires
stage runtime config/restart outside this script.
Economy DB setup is repeatable only with `TELEGRAM_E2E_ALLOW_DB_MUTATION=1`: it resets the
tester balance, bid, safe balance, state and old active credit sessions under the stage DB guard.
Credit and bankruptcy checks compare against before snapshots so stale rows cannot satisfy them.
`prod-smoke` reuses the tester bot and target test chat, but performs only Telegram-visible checks.
It fails if production `/help` still exposes legacy fork text, so it can confirm the command-contract
cleanup after rollout.

Ожидаемый результат:
- сценарий завершается успешно;
- stage-бот отвечает в staging-чате;
- `event_history` содержит события тестера;
- stage-БД изменилась, production-БД не затронута.
- `prod-smoke` завершается успешно после rollout и не выполняет mutating economy flows.

---

## Dependencies

- TASK-018: безопасная изоляция staging/prod.
- Отдельный staging Telegram chat.
- Отдельный tester bot token.
- Bot-to-Bot Communication Mode в BotFather.

---

## Out Of Scope

- Замена unit/integration тестов.
- Мутирующие E2E-сценарии против production.
- Автоматическое нажатие inline-кнопок через Bot API.
- Использование userbot/MTProto/Telethon для обхода ограничений callback-кнопок.

---

## References

- Telegram announcement: https://telegram.org/blog/ai-bot-revolution-11-new-features/ru
- Bot-to-Bot Communication: https://core.telegram.org/bots/features#bot-to-bot-communication
- Testing your bot: https://core.telegram.org/bots/features#testing-your-bot
- `docs/STAGING_PROD_RUNBOOK.md`
- `tests/integration/`
