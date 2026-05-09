# AGENTS.md — Left4Casino Bot

## Обзор проекта

**Left4Casino** — Telegram-бот для виртуального казино с ИИ-банкиром, системой ставок, PvP-дуэлями на кубиках, сейфом для защиты очков, переводами между игроками, счастливыми мигами, ограблением банка и ежедневной статистикой. Проект построен на `aiogram 3.x` с асинхронной архитектурой.

### Scope: границы репозитория

- **n8n-install не трогаем ВООБЩЕ.** Родительский репозиторий (n8n-install, docker-compose, Caddy, скрипты установки и т.п.) не изменяется.
- **Все работы ведутся в telegram-casino-bot** и в файлах уровня python-runner, относящихся к боту: код — в `telegram-casino-bot/`, спецификации и статусы — в `docs/specs/`, `logs/`, `status.yaml`, `pyproject.toml`, скрипты линта/тестов в `scripts/` внутри python-runner.
- Коммиты в родительский репозиторий (n8n-install) не делаем; при необходимости коммитить только изменения внутри `python-runner/` (в т.ч. подмодуль `telegram-casino-bot`).

---

## 🏗 Development Workflow (Cursor-Native v3.0)

Разработка ведётся в **Cursor Agent Mode** с прямым контролем контекста и инструментов.

### Workflow Lifecycle

1. **Discovery & Contract**: Обсуждаем задачу в чате → создаем спецификацию в `docs/specs/`.
2. **Implementation**: Cursor (в режиме Agent) пишет код по контракту, используя LSP (Pyright).
3. **Verification**: Запуск тестов и линтеров прямо в Composer.
4. **Documentation**: Фиксация итогов в `logs/dev_diary.md` и обновление `status.yaml`.

### Core Roles (Context Modes)

Используйте переключение контекста через `.cursorrules` и промпты:

| Роль | Задача | Инструменты |
| :--- | :--- | :--- |
| **Architect** | Анализ требований и создание тех. контрактов. | `@docs`, `@status.yaml`, `@architecture.md` |
| **Engineer** | Реализация типизированного кода с семантическими регионами. | `@LSP`, `@Pyright`, `# [START SPEC]` |
| **QA** | Написание тестов и поиск edge-cases. | `@pytest`, `@ruff`, XML Bug Reports |
| **Tech Lead** | Ревью, проверка TQS и финализация (Git). | `@git`, `@diff`, TQS Score |

### Project Skills (Action Protocols)

Эти «скиллы» — стандартные протоколы действий для Cursor:

#### 1. `skill:spec` (Инициализация задачи)
**Когда**: Поступила новая идея.
**Действие**: 
- Итеративный диалог для уточнения.
- Создание `docs/specs/[TASK_ID].md` с REQ-ID и контрактами.
- Регистрация задачи в `status.yaml` со статусом `SPEC_READY`.

#### 2. `skill:code` (Реализация)
**Когда**: Статус `SPEC_READY`.
**Действие**:
- Реализация кода строго по REQ-ID.
- **Обязательная разметка**: семантические регионы для критичной логики (game balance, атомарные операции, долги) — формат в `docs/SEMANTIC_REGIONS_GUIDE.md`: `# [START SPEC:{ID}:{NAME}]` … `# [END SPEC:{ID}]`.
- Самопроверка через `pyright` и `ruff`.
- Обновление `status.yaml` → `CODE_WRITTEN`.
- **Автопереход**: если написание кода завершилось успешно и нет ни малейших сомнений — сразу переходить к `skill:validate` (не останавливаться на ручном переключении).

#### 3. `skill:validate` (Тестирование и Ревью)
**Когда**: Статус `CODE_WRITTEN`.
**Действие**:
- Запуск тестов: **обязательно** `./scripts/test.sh` (создаёт/использует `.venv`, ставит зависимости; не запускать сырой `pytest` без venv — возможен конфликт с системным Pydantic). Написание/запуск `tests/test_[ID].py` при необходимости.
- Запуск линта: `./scripts/lint.sh`.
- Если баг или ошибки линтера/типов — **автоматически** исправлять (правки в коде или тестах), затем снова запускать проверки; **не переходить к archive, пока тесты и линт не пройдут**.
- Если успех — проверка TQS (Technical Quality Score), обновление `status.yaml` → `READY_TO_MERGE`.
- **Автопереход**: при успешной валидации — сразу переходить к `skill:archive`.

#### 4. `skill:archive` (Финализация)
**Когда**: Статус `READY_TO_MERGE`.
**Действие**:
- Запись в `logs/dev_diary.md` (почему сделано именно так).
- **Перемещение** спеки в `docs/specs/archive/` — только командой `mv` (никогда не удалять файл и не создавать копию вручную).
- Обновление `status.yaml` → `DONE`, `spec`: путь к файлу в `archive/`.
- `git commit` с ID задачи.

### Context Management

- **LSP (Pyright)**: Ваши "глаза". Всегда используйте контекст типов для предотвращения галлюцинаций.
- **status.yaml**: Единственный источник правды о состоянии проекта.
- **.cursorrules**: Глобальные инструкции для AI (стиль кода, запрещенные приемы).

### Staging / Production Workflow

Для безопасной разработки Telegram-бота используется раздельная схема **stage/prod**.

**Основные документы:**
- Спецификация: `docs/specs/TASK-018_SAFE_STAGING_PROD_WORKFLOW.md`
- Runbook: `docs/STAGING_PROD_RUNBOOK.md`
- Шаблон env для prod: `env/prod.example.env`
- Шаблон env для stage: `env/stage.example.env`
- Шаблон systemd для prod: `left4casino-prod.example.service`
- Шаблон systemd для stage: `left4casino-stage.example.service`

**Текущая фактическая схема на сервере:**
- **Prod (живой):** `/root/n8n-install/python-runner` → запускается в Docker контейнере `python-runner`
- **Stage (живой):** `/opt/left4casino/python-runner-stage` → запускается через `left4casino-stage.service`
- **Prod worktree (подготовлен, но не используется в runtime):** `/opt/left4casino/python-runner-prod`

**Правила для следующих агентов:**
- не смешивать stage и prod БД;
- не использовать один и тот же bot token для двух сред;
- перед изменениями в production делать backup `settings.toml` и `bot/casino.db`;
- не переводить production с Docker на systemd без явного запроса пользователя;
- при доработке процесса stage/prod сначала читать `TASK-018` и `docs/STAGING_PROD_RUNBOOK.md`.

### Semantic Regions

Критичный код (game balance, атомарные транзакции, взаимозачёт долгов) размечен семантическими регионами. Формат и список файлов — в `docs/SEMANTIC_REGIONS_GUIDE.md`.

- При встрече маркеров `# [START SPEC:...]`: читать REQ и Source, **не менять** код внутри региона без явного запроса пользователя.
- При рефакторинге: упоминать, что регион помечен как критичный (SPEC_ID).
- При реализации по спецификации: **обязательно** добавлять регионы для новой логики по формату из гайда.
- Проверка: `python scripts/verify_regions.py`.

### Best Practices 2026

1. **MCP (Model Context Protocol)**: Если нужны внешние инструменты (БД, API n8n), подключайте их через MCP-серверы.
2. **Composer (Ctrl+I)**: Всегда используйте режим **Agent** для многофайловых правок.
3. **Semantic Regions**: Не удаляйте маркеры `# [START SPEC]`, они помогают AI ориентироваться в больших файлах.
4. **No Loop Policy**: Если AI зациклился (не может поправить тест 3 раза), вмешайтесь вручную или уточните спецификацию.

### Краткий справочник команд

| Команда | Описание |
|---------|----------|
| `/start`, `/balance` | Баланс и базовая информация |
| `/bid [N]` | Установить множитель ставки (all-in если > баланса) |
| `/stats [@user]` | Персональная статистика игрока |
| `/top` | Топ-10 игроков группы |
| `/give <сумма> @user` | Перевод очков другому игроку |
| `/credit` | Запрос кредита у ИИ-банкира (при balance ≤ 0) |
| `/dice <ставка>` | Вызов на PvP дуэль на кубиках |
| `/take <сумма> @user` | Взыскание долга с должника |
| `/safe [±сумма]` | Сейф: просмотр / положить / снять очки |
| 🎰 | Слоты — отправить dice для игры |
| 🏦 | Ограбление Банка — ежедневный ивент (автоматически) |

---

## Структура проекта

```
python-runner/
├── main.py                     # Точка входа, запускает бота
├── pyproject.toml              # Метаданные, зависимости, ruff/pyright/pytest
├── requirements.txt            # Сгенерирован из pyproject.toml (CI/Docker)
├── groups.json                 # Маппинг chat_id → название группы
├── docs/
│   └── specs/                  # Спецификации фич (архив реализованных задач)
├── logs/
│   └── dev_diary.md           # История разработки и принятых решений
└── telegram-casino-bot/        # Основной код бота
    ├── bot/
    │   ├── __main__.py         # Инициализация бота, диспетчера, планировщика
    │   ├── config_reader.py    # Парсинг settings.toml
    │   ├── db.py               # SQLite ORM (aiosqlite)
    │   ├── dice_check.py       # Логика расчёта выигрыша по значению dice
    │   ├── handlers/           # Обработчики команд
    │   │   ├── default_commands.py  # /start, /balance, /stats, /bid
    │   │   ├── spin.py              # Логика dice/slots
    │   │   ├── group_games.py       # Обработка 🎰 в группах (+ heist mode)
    │   │   ├── transfer.py          # /give — переводы
    │   │   ├── ai_credit.py         # /credit — ИИ-кредиты
    │   │   ├── dice_fight.py        # /dice, /take — PvP дуэли
    │   │   └── safe.py              # /safe — безопасный счёт
    │   ├── services/           # Бизнес-логика
    │   │   ├── ai.py           # AIClient — взаимодействие с LLM
    │   │   ├── daily_stats.py  # DailyStatsService — ежедневные отчёты
    │   │   ├── happy_moment.py # HappyMomentService — счастливый миг
    │   │   ├── heist.py        # HeistService — ограбление банка
    │   │   ├── group_tracker.py # Отслеживание участников групп
    │   │   └── backfill.py     # Миграции данных
    │   ├── middlewares/        # Middleware
    │   │   ├── throttling.py   # Защита от спама
    │   │   ├── restrictions.py # Ограничения по чатам
    │   │   ├── tracker.py      # Трекинг активности
    │   │   └── logging.py      # Логирование запросов
    │   ├── locale/             # Локализация (Fluent)
    │   └── utils/              # Утилиты
    └── settings.example.toml   # Пример конфигурации
```

---

## Архитектура

### Слои приложения

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot API                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     Middlewares                              │
│  ChatRestriction → GroupTracker → Throttling → Logging       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      Handlers (Routers)                      │
│  default_commands │ group_games │ transfer │ ai_credit │ dice_fight │ safe │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       Services                               │
│   AIClient │ DailyStatsService │ HappyMomentService │ GroupTracker │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    Database (SQLite)                         │
│   users │ event_history │ ai_credit_sessions │ user_groups │ dice_challenges │ player_debts │
└─────────────────────────────────────────────────────────────┘
```

---

## Ключевые компоненты

### 1. Database (`bot/db.py`)

Асинхронный слой работы с SQLite через `aiosqlite`.

**Таблицы:**
| Таблица | Назначение |
|---------|------------|
| `users` | Профили: balance, safe_balance, bid, state, nickname, статистика |
| `event_history` | Лог всех событий: win/loss/transfer/bankruptcy/dice_challenge_win/dice_challenge_loss/dice_challenge_draw/happy_moment_win/debt_created/debt_paid |
| `ai_credit_sessions` | Сессии кредитного диалога с ИИ |
| `ai_dialogue_messages` | История сообщений в AI-сессии |
| `user_groups` | Связь user ↔ chat для лидербордов |
| `dice_challenges` | PvP дуэли на кубиках |
| `player_debts` | Долги между игроками |

**Ключевые методы:**
- `get_balance()`, `update_balance()`, `set_balance()`
- `get_safe_balance()`, `safe_deposit()`, `safe_withdraw()` — защищённый счёт
- `transfer_money()` — атомарный перевод с логированием
- `create_credit_session()`, `close_credit_session()`
- `get_daily_stats()` — агрегация для отчётов
- `create_dice_challenge()`, `accept_challenge()`, `record_roll()`, `resolve_challenge()` — дуэли
- `get_debt()`, `add_debt()`, `reduce_debt()`, `get_total_debt_to_others()` — долги

### 2. AIClient (`bot/services/ai.py`)

Интеграция с LLM (OpenAI/OpenRouter) для ИИ-банкира.

**Функции:**
- `generate_initial_greeting()` — генерация задания (анекдот, тост, загадка)
- `generate_response()` — оценка ответа пользователя с учётом:
  - Соответствия теме
  - Креативности
  - Эвристики AI-генерации (длина, типографика, структура)

**Формат ответа:**
```json
{
  "content": "Комментарий банкира",
  "completion_data": {
    "done": true,
    "score": 10,
    "reward": 75,
    "comment": "..."
  }
}
```

### 3. Handlers

#### `/credit` (`handlers/ai_credit.py`)
```
Условия:
├── balance <= 0
├── Нет активной сессии
└── Прошёл cooldown (15 мин)

Flow:
1. create_credit_session()
2. set state = IN_DIALOGUE
3. generate_initial_greeting() → send
4. Фильтр InDialogueFilter() ловит ответы
5. generate_response() → оценка
6. update_balance() + close_session()
```

#### `/give <amount> @user` (`handlers/transfer.py`)
Атомарный перевод с проверкой баланса и записью в event_history.

#### `/bid [N]` (`handlers/default_commands.py`)
Установка множителя ставки. Значение > balance → автоматический all-in.

#### `/stats [@username]` (`handlers/group_games.py`)
Индивидуальная статистика игрока.
- `/stats` — своя статистика (баланс, сейф, слоты, дуэли, банкротства, долги, позиция в рейтинге)
- `/stats @username` — статистика другого игрока
- Работает только в групповых чатах

#### `/top` (`handlers/group_games.py`)
Рейтинг топ-10 игроков группы.
- Показывает баланс, статистику слотов, дуэли, банкротства, долги
- Медали 🥇🥈🥉 для топ-3
- Если вызывающий не в топ-10 — показывает его позицию отдельно
- Throttle: 5 секунд
- Работает только в групповых чатах

#### `/dice <ставка>` (`handlers/dice_fight.py`)
PvP дуэль на кубиках.
```
Flow:
1. Создание вызова с inline-кнопками
2. Оппонент принимает вызов
3. Оба игрока бросают 🎲 (таймаут 5 мин — автобросок)
4. Победитель забирает ставку
5. Проигравший может уйти в долг до -100
```

#### `/take <сумма> @user` (`handlers/dice_fight.py`)
Взыскание долга с игрока.
- Можно забрать только у того, кто конкретно должен
- Нельзя забрать больше чем долг или баланс должника

#### `/safe [сумма]` (`handlers/safe.py`)
Безопасный счёт (сейф) — защищённое хранилище очков.
- `/safe` — показать баланс сейфа
- `/safe 50` — положить 50 очков в сейф
- `/safe -50` — снять 50 очков из сейфа
- Очки в сейфе **не участвуют** в играх (слоты, дуэли)
- Долги **нельзя взыскать** из сейфа (`/take` работает только с balance)
- Можно класть в сейф при наличии долгов
- **Нельзя класть в сейф** во время активной дуэли или вызова
- Работает только в групповых чатах

### 4. Middlewares

| Middleware | Функция |
|------------|---------|
| `ChatRestrictionMiddleware` | Whitelist чатов, блокировка ЛС |
| `GroupTrackerMiddleware` | Обновление user_groups при активности |
| `ThrottlingMiddleware` | Rate-limit: 2 сек на спин, 5 сек на /top, 1 сек на остальное |
| `LoggingMiddleware` | Структурное логирование через structlog |

### 5. Scheduler (APScheduler)

- **00:00** — `send_daily_reports()` во все allowed_chat_ids
- **00:00** — `generate_happy_moment_schedule()` — генерация расписания счастливых мигов на день
- **23:30** — `send_draft_report()` админу (preview)
- **каждую минуту** — `check_expired_challenges()` для истечения неактивных вызовов
- **каждые 30 сек** — `check_duel_timeouts()` для автоброска при таймауте
- **динамически** — `start_happy_moment()` / `end_happy_moment()` — запуск и завершение счастливых мигов

---

## Database Migrations

Схема БД версионируется через SQL-миграции в каталоге `migrations/`.

**Применение миграций:**
```bash
# из корня python-runner
python migrations/migration_runner.py
```

**Создание миграции:** новый файл `migrations/00X_description.sql` с секциями `-- UPGRADE` и `-- DOWNGRADE` (см. `migrations/template.sql`). Нумерация: 001, 002, …; имя — lowercase, осмысленное (например `002_add_heist_tables.sql`).

**Workflow при изменении схемы:** создать файл миграции → выполнить `python migrations/migration_runner.py` → протестировать → закоммитить миграцию вместе с кодом.

**Откат:** автоматического downgrade нет; при проблемах — восстановление из backup БД или ручной запуск SQL из секции DOWNGRADE.

Подробнее: `migrations/README.md`.

---

## Конфигурация

### settings.toml
```toml
[bot]
token = "..."
fsm_mode = "redis"  # или "memory"

[redis]
dsn = "redis://..."

[game_config]
starting_points = 50
throttle_time_spin = 2
throttle_time_other = 1

[chat_restrictions]
block_private_chats = false
allowed_chat_ids = [-1001234567890]

[ai]
provider = "openrouter"
model = "deepseek/deepseek-chat"
credit_cooldown_minutes = 15

[reports]
timezone = "Asia/Yekaterinburg"
admin_id = 123456789

[dice_fights]
challenge_timeout_minutes = 5
roll_timeout_minutes = 5
max_debt = 100
min_bet = 1

[happy_moment]
enabled = true
events_per_day = 2
active_hours_weight = 90  # % в активное время (08:00-02:00)
active_hours_start = "08:00"
active_hours_end = "02:00"
# Тиры: [[happy_moment.tiers]] duration_minutes, multiplier
```

### Переменные окружения
```bash
OPENROUTER_API_KEY=sk-or-v1-...  # Ключ для LLM
CONFIG_FILE_PATH=/path/to/settings.toml  # Опционально
```

---

## Механика игры

### Slots (🎰)
Результат dice (1-64) маппится на комбинацию барабанов.

**Выигрыши:**
| Комбинация | Очки |
|------------|------|
| Три одинаковых | +7 |
| 777 | +10 |
| BAR BAR BAR | +5 |
| Проигрыш | -1 |

**Super Jackpot (15% при выигрыше):**
| Множитель | Шанс |
|-----------|------|
| x2 Mini | 65% |
| x3 Major | 25% |
| x5 Mega | 9% |
| x10 Grand | 1% |

Итоговый выигрыш = `базовые_очки × bid × jackpot_multiplier`

### Банкротство
При `balance <= 0` после проигрыша:
- Запись `bankruptcy` в event_history
- Инкремент `bankruptcy_count` в users
- Отправка стикера "game over"

### PvP Дуэли (🎲)

**Команда `/dice <ставка>`:**
- Создаёт вызов на дуэль с inline-кнопками
- Минимальная ставка: 1, максимальная: баланс + 100 (долг)
- Оппонент принимает нажатием кнопки
- Оба игрока бросают 🎲 (обычные кости 1-6)
- Побеждает тот, у кого больше; при ничьей — возврат ставок

**Долги:**
- Если проигравший не может оплатить полностью, создаётся долг
- Максимальный долг: -100 очков
- Долг хранится в таблице `player_debts`
- Баланс игрока НЕ уходит в минус — минус это долг
- **Взаимозачёт:** если A должен B и B должен A, долги автоматически взаимоуничтожаются
- Существующие долги уменьшают доступный лимит для новых ставок

**Команда `/take <сумма> @user`:**
- Взыскание долга с должника
- Можно забрать только свой долг (кто конкретно тебе должен)
- Нельзя забрать больше чем баланс должника

**Таймауты:**
- Вызов без принятия: 5 минут → истекает
- Дуэль без броска: 5 минут → бот бросает автоматически

### Счастливый миг (Happy Moment)

Временный бонусный период, когда все выигрыши в слотах умножаются.

**Расписание:**
- 2 раза в сутки в случайное время
- 90% вероятность в 08:00–02:00, 10% ночью
- Генерируется в 00:00 или при старте бота

**Таблица множителей:**
| Длительность | Множитель |
|--------------|-----------|
| 1 мин        | ×5        |
| 2 мин        | ×4        |
| 3 мин        | ×3        |
| 5 мин        | ×2.5      |
| 10 мин       | ×2        |
| 15 мин       | ×1.5      |

**Механика:**
- При старте отправляется уведомление во все группы
- Множитель стекается с джекпотом: `базовые_очки × bid × jackpot × happy_moment`
- Выигрыши логируются как `happy_moment_win`

**Названия (случайный выбор):**
- Счастливый миг, Золотой час, Бонус-тайм, Джекпот-раш
- Звёздный час, Фортуна улыбается, Время удачи, Щедрый момент

### Ограбление Банка (Heist)

Ежедневный ивент, во время которого все спины слотов наполняют общий банк. Последний игрок забирает весь банк за вычетом комиссии крупье.

**Расписание:**
- 1 раз в сутки в случайное время (только в активные часы 08:00–02:00)
- Предупреждение за 10 минут до старта
- Генерируется в 00:00 или при старте бота

**Экономика:**
- Все параметры рассчитываются относительно **B** — суммы выигрышей чата за вчера
- `pot_cap` = B × 5% — макс. размер банка → досрочная Фаза 2 (снижено из-за новой логики)
- `min_pot` = B × 1% — мин. банк для завершения без продления
- `seed` = B × random(0.5-1.5%) — начальный взнос крупье (если никто не играет)
- `commission` = % от банка — доля крупье (уничтожается из экономики, настраивается в конфиге)
- Fallback: если B < 1000 → B = 1000
- **Дефляционная модель**: чистая инфляция = 0%, деньги только перераспределяются

**Двухфазная система:**
```
Фаза 1: "ОГРАБЛЕНИЕ" (10-25 мин, случайно)
├── Если pot = 0 после 5 мин → seed
├── Если pot ≥ pot_cap → досрочный переход в Фазу 2
└── Таймер истёк:
    ├── pot < min_pot → продлить на +5 мин (однократно)
    └── pot ≥ min_pot → переход в Фазу 2

Фаза 2: "ТРЕВОГА" (2-5 мин, случайно)
└── Таймер истёк → КОНЕЦ ИВЕНТА

Hard cap: 30 мин максимум
```

**Механика спинов (НОВАЯ ЛОГИКА):**
- Проигрыш: `balance -= bid`, `pot += bid` (ставка списывается и идёт в банк)
- Выигрыш: `balance += calculated_win` (игрок получает выигрыш как обычно, банк НЕ пополняется)
- Учитывается: base score, bid, super jackpot, happy moment (если активен)
- Последний игрок обновляется при каждом спине

**Завершение:**
- Победитель получает: `pot × (100 - commission_pct)%`
- Комиссия крупье: `pot × commission_pct%` (уничтожается)
- Если никто не играл → ивент завершается без выплаты

**Event types:**
- `heist_start` — старт ивента
- `heist_contribution` — проигрыш во время ивента (ставка → в банк)
- `win` / `loss` — обычные события (с флагом `during_heist: true` в metadata)
- `heist_win` — выплата победителю
- `heist_commission` — комиссия крупье
- `heist_seed` — seed от крупье
- `heist_no_winner` — ивент без участников

---

## Добавление новых функций

### Новый Handler
```python
# bot/handlers/my_feature.py
from aiogram import Router
from aiogram.filters import Command
from bot.db import Database

router = Router()

@router.message(Command("mycommand"))
async def cmd_mycommand(message, db: Database):
    # Логика
    await message.reply("Done!")
```

Регистрация в `__main__.py`:
```python
from bot.handlers import my_feature
dp.include_router(my_feature.router)
```

### Новое событие в БД
1. Добавить тип в `event_history.event_type`
2. Использовать `db.add_event(event_id, user_id, "my_event", amount, metadata, chat_id)`

### Модификация AI-промптов
Файл: `bot/services/ai.py`
- Задания: массивы `tasks` и `topics` в `generate_initial_greeting()`
- Оценка: системный промпт в `generate_response()`

---

## Запуск

### Локально
```bash
cd python-runner
pip install -e .                  # editable install (рекомендуется)
# pip install -e ".[dev]"         # + ruff, pyright, pytest для разработки
# или для CI/Docker-совместимости:
# pip install -r requirements.txt
export OPENROUTER_API_KEY=...
python main.py
```

### Docker
```bash
cd telegram-casino-bot
cp settings.example.toml settings.toml
# Отредактировать settings.toml
docker-compose up --profile all -d
```

---

## Зависимости

| Пакет | Версия | Назначение |
|-------|--------|------------|
| aiogram | ≥3.18.0 | Telegram Bot API |
| aiosqlite | ≥0.19.0 | Async SQLite |
| openai | ≥1.0.0 | LLM клиент |
| apscheduler | ≥3.10.4 | Планировщик задач |
| structlog | ≥25.1.0 | Логирование |
| redis | ≥5.2.1 | FSM storage |
| python-dotenv | ≥1.0.0 | Env-переменные |

---

## Quality Checks

Перед push рекомендуется запускать линтеры и проверку типов:

```bash
# Полная проверка (ruff lint + format check + pyright)
./scripts/lint.sh

# Или по отдельности
ruff check .
ruff format --check .
pyright
```

Установка pre-commit (опционально): `pre-commit install` — тогда проверки запустятся автоматически при каждом коммите.

---

## CI/CD (TASK-012)

В каталоге `.github/workflows/` настроены три workflow:

| Workflow | Триггер | Назначение |
|----------|---------|------------|
| `test.yml` | push, PR в main | Unit- и integration-тесты параллельно, coverage → Codecov |
| `lint.yml` | push, PR в main | ruff check, ruff format --check, pyright |
| `deploy.yml` | push в main, workflow_dispatch | Сборка Docker-образа, публикация в ghcr.io; опционально deploy по SSH |

Если репозиторий — монорепо (например n8n-install), скопируйте `.github/workflows` в корень репозитория, чтобы GitHub Actions их подхватил. В Branch protection для main можно включить required checks: Unit Tests, Integration Tests, Ruff, Pyright.

---

## Полезные команды

```bash
# Проверка структуры БД
sqlite3 telegram-casino-bot/bot/casino.db ".schema"

# Просмотр event_history
sqlite3 telegram-casino-bot/bot/casino.db "SELECT * FROM event_history ORDER BY created_at DESC LIMIT 20"

# Сброс состояния пользователя (если завис в IN_DIALOGUE)
sqlite3 telegram-casino-bot/bot/casino.db "UPDATE users SET state='IDLE' WHERE user_id=123456"
```

---

## Контакты и лицензия

- Telegram: [@Left4CasinoBot](https://t.me/Left4CasinoBot)
- Основан на: [MasterGroosha/telegram-casino-bot](https://github.com/MasterGroosha/telegram-casino-bot)
- Лицензия: MIT
