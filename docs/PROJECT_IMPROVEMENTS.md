# Рекомендации по улучшению структуры проекта

Дата: 2026-02-15
Статус: Предложения для обсуждения

---

## ✅ Выполнено

1. **Консолидация workflow-документации**: Информация из `AGENTS_NEW.MD` интегрирована в `AGENTS.md`
2. **Организация спецификаций**: Все спеки перенесены в `docs/specs/`
3. **Удаление дубликатов**: `AGENTS_NEW.MD` удалён

---

## 🔄 Предложения по дальнейшему улучшению

### 1. Структура директорий

#### Текущая структура
```
python-runner/
├── main.py
├── requirements.txt
├── groups.json
├── docs/specs/
└── telegram-casino-bot/
```

#### Предлагаемая структура
```
python-runner/
├── main.py
├── pyproject.toml          # Современная замена setup.py + requirements.txt
├── README.md               # Быстрый старт для разработчиков
├── docs/
│   ├── specs/              # ✅ Уже создано
│   ├── architecture.md     # Высокоуровневые диаграммы и решения
│   └── api/                # API-документация (если планируется)
├── logs/
│   └── dev_diary.md        # История решений (TODO: создать)
├── tests/
│   ├── unit/               # Юнит-тесты
│   ├── integration/        # Интеграционные тесты
│   └── conftest.py         # Pytest фикстуры
├── data/
│   └── groups.json         # Конфигурационные данные
├── scripts/
│   ├── migrate_db.py       # Миграции БД
│   └── seed_data.py        # Тестовые данные
└── telegram-casino-bot/
    └── bot/
        ├── handlers/
        ├── services/
        ├── middlewares/
        ├── models/         # Pydantic модели для типизации
        └── utils/
```

**Обоснование:**
- `pyproject.toml` — современный стандарт для Python-проектов (PEP 518)
- `logs/dev_diary.md` — для фиксации принятых решений по workflow
- `tests/` — разделение unit/integration тестов
- `data/` — конфигурационные файлы отдельно от кода
- `scripts/` — утилиты для работы с БД и данными

---

### 2. Управление конфигурацией

#### Текущее состояние
```
telegram-casino-bot/
├── settings.example.toml
└── bot/casino.db
```

#### Предложения

**A. Разделение по окружениям:**
```
config/
├── settings.base.toml       # Базовые настройки
├── settings.dev.toml        # Локальная разработка
├── settings.prod.toml       # Продакшн
└── settings.test.toml       # Тестирование
```

**B. Миграция на Pydantic Settings:**
```python
# bot/config.py
from pydantic_settings import BaseSettings

class BotConfig(BaseSettings):
    token: str
    fsm_mode: str = "redis"
    
    class Config:
        env_file = ".env"
        env_prefix = "BOT_"
```

**Преимущества:**
- Валидация на старте приложения
- Автодополнение в IDE
- Документация через типы

---

### 3. База данных

#### Текущее состояние
- Ручные SQL-запросы в `bot/db.py`
- Нет системы миграций

#### Предложения

**A. Добавить Alembic для миграций:**
```
alembic/
├── versions/
│   ├── 001_initial_schema.py
│   ├── 002_add_heist_tables.py
│   └── 003_add_safe_balance.py
└── env.py
```

**B. Рассмотреть SQLAlchemy (опционально):**
```python
# bot/models/user.py
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)
    balance = Column(Float, default=50)
    safe_balance = Column(Float, default=0)
```

**Или остаться на aiosqlite с улучшениями:**
- Добавить репозиторный паттерн (отделить БД-логику от бизнес-логики)
- Создать `migrations/` с SQL-скриптами

---

### 4. Типизация и качество кода

#### Предложения

**A. Добавить pyproject.toml с настройками линтеров:**
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pyright]
typeCheckingMode = "strict"
reportMissingTypeStubs = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**B. Добавить pre-commit hooks:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
```

**C. Создать `bot/models/` с Pydantic схемами:**
```python
# bot/models/events.py
from pydantic import BaseModel
from datetime import datetime

class GameEvent(BaseModel):
    event_id: str
    user_id: int
    event_type: str
    amount: int
    created_at: datetime
    metadata: dict = {}
```

---

### 5. Тестирование

#### Текущее состояние
- Тестов нет

#### Предложения

**A. Создать структуру тестов:**
```
tests/
├── unit/
│   ├── test_dice_check.py      # Тест логики расчёта выигрышей
│   ├── test_heist_service.py   # Тест экономики ограбления
│   └── test_happy_moment.py    # Тест генерации расписания
├── integration/
│   ├── test_handlers.py        # Тест полных флоу команд
│   └── test_db.py              # Тест работы с БД
└── conftest.py                 # Фикстуры (мок бота, БД)
```

**B. Минимальный набор тестов для начала:**
1. `test_dice_check.py` — самая критичная логика
2. `test_heist_economy.py` — проверка балансировки
3. `test_ai_credit_flow.py` — end-to-end тест кредитования

**C. Добавить CI/CD:**
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest tests/
```

---

### 6. Мониторинг и логирование

#### Текущее состояние
- `structlog` настроен в middlewares

#### Предложения

**A. Структурировать логи:**
```
logs/
├── app.log              # Общий лог приложения
├── events.jsonl         # Игровые события (JSON Lines)
├── errors.log           # Только ошибки
└── dev_diary.md         # Ручные записи разработчиков
```

**B. Добавить метрики (опционально):**
```python
# bot/metrics.py
from prometheus_client import Counter, Histogram

spins_total = Counter('casino_spins_total', 'Total spins', ['result'])
heist_duration = Histogram('heist_duration_seconds', 'Heist event duration')
```

**C. Алерты в Telegram (для критичных ошибок):**
```python
# bot/utils/alerts.py
async def send_admin_alert(bot, error: Exception, context: dict):
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"⚠️ Критическая ошибка:\n{error}\n\nКонтекст: {context}"
    )
```

---

### 7. Документация

#### Предложения

**A. Создать `docs/architecture.md`:**
```markdown
# Архитектура Left4Casino

## Основные принципы
- Event Sourcing через event_history
- Дефляционная экономика (инфляция = 0%)
- Асинхронная обработка через aiogram 3.x

## Важные решения
- Почему SQLite: простота, достаточная производительность
- Почему не Redis для event_history: нужна персистентность
- Почему двухфазная система heist: баланс риска и вовлечённости
```

**B. API-документация (если планируется):**
```
docs/api/
├── handlers.md          # Описание всех команд
├── services.md          # Описание сервисов
└── events.md            # Типы событий в event_history
```

**C. Добавить docstrings в критичные функции:**
```python
async def resolve_challenge(self, challenge_id: int, db: Database) -> dict:
    """
    Завершает дуэль и выплачивает выигрыш.
    
    Args:
        challenge_id: ID дуэли
        db: Инстанс Database
        
    Returns:
        dict: {
            "winner_id": int,
            "loser_id": int,
            "amount": int,
            "debt_created": int
        }
        
    Raises:
        ValueError: Если дуэль не завершена или не найдена
    """
```

---

### 8. Docker и деплой

#### Предложения

**A. Multi-stage Dockerfile:**
```dockerfile
# Dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS dev
COPY . .
CMD ["python", "main.py"]

FROM base AS prod
COPY telegram-casino-bot telegram-casino-bot
COPY main.py .
RUN useradd -m casino
USER casino
CMD ["python", "main.py"]
```

**B. Docker Compose для разработки:**
```yaml
# docker-compose.dev.yml
services:
  bot:
    build:
      context: .
      target: dev
    volumes:
      - .:/app
    env_file: .env.dev
    depends_on:
      - redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

---

### 9. Безопасность

#### Предложения

**A. Создать `.env.example`:**
```bash
# .env.example
OPENROUTER_API_KEY=sk-or-v1-...
CONFIG_FILE_PATH=/path/to/settings.toml

# Не коммитить реальные ключи!
```

**B. Добавить в `.gitignore`:**
```
# .gitignore
.env
.env.local
*.db
*.db-journal
logs/*.log
__pycache__/
.pytest_cache/
.ruff_cache/
```

**C. Валидация входных данных:**
```python
# bot/utils/validators.py
from pydantic import BaseModel, Field, validator

class TransferRequest(BaseModel):
    amount: int = Field(gt=0, le=10000)
    recipient_id: int
    
    @validator('amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        return v
```

---

### 10. Workflow-инструменты

#### Предложения

**A. Создать `status.yaml` (как упомянуто в workflow):**
```yaml
# status.yaml
version: "1.0"
current_sprint: "2026-02-W07"

tasks:
  - id: FEAT-001
    name: "Refactor database layer"
    status: SPEC_READY
    assignee: cursor-agent
    priority: HIGH
    
  - id: BUG-042
    name: "Fix heist commission calculation"
    status: CODE_WRITTEN
    assignee: cursor-agent
    priority: MEDIUM
```

**B. Создать `logs/dev_diary.md`:**
```markdown
# Development Diary

## 2026-02-15: Reorganization of project structure

**Decision**: Move all specs to `docs/specs/`
**Reasoning**: Specs were cluttering root directory
**Alternatives considered**: Create `archive/`, use wiki
**Trade-offs**: Need to update references in AGENTS.md
**Result**: Cleaner root, better navigation

## 2026-01-23: Happy Moment implementation

**Decision**: Use weighted random scheduling
**Reasoning**: ...
```

**C. Semantic regions в коде:**
```python
# bot/services/heist.py

# [START SPEC:HEIST-001:Economy Calculations]
def calculate_pot_cap(self, base_winnings: int) -> int:
    """Calculate maximum pot size."""
    return int(base_winnings * 0.05)
# [END SPEC:HEIST-001]

# [START SPEC:HEIST-002:Phase Transitions]
async def transition_to_phase_2(self):
    """Transition heist to alarm phase."""
    # ...
# [END SPEC:HEIST-002]
```

---

## 📊 Приоритизация

### High Priority (начать в первую очередь)
1. ✅ **Организация спецификаций** → Выполнено
2. 🔄 **Создать `logs/dev_diary.md`** → Начать записывать решения
3. 🔄 **Добавить `pyproject.toml`** → Современный стандарт
4. 🔄 **Настроить ruff + pyright** → Улучшить качество кода
5. 🔄 **Базовые unit-тесты** → `test_dice_check.py`, `test_heist_economy.py`

### Medium Priority (следующие шаги)
6. 🔄 **Pydantic модели** → Типизация событий и конфигов
7. 🔄 **Структура тестов** → `tests/unit/`, `tests/integration/`
8. 🔄 **Миграции БД** → Alembic или SQL-скрипты
9. 🔄 **Разделение config/** → dev/prod окружения
10. 🔄 **Docker multi-stage** → Оптимизация образов

### Low Priority (по желанию)
11. 🔄 **Prometheus метрики** → Если нужен мониторинг
12. 🔄 **CI/CD** → GitHub Actions
13. 🔄 **API документация** → Если планируется расширение
14. 🔄 **SQLAlchemy** → Только если БД сильно вырастет

---

## 🤔 Вопросы для обсуждения

1. **Тестирование**: Нужны ли сейчас полноценные тесты или подождём до стабилизации фич?
2. **Миграции БД**: Использовать Alembic или достаточно SQL-скриптов?
3. **SQLAlchemy**: Переходить или оставить aiosqlite + репозиторный паттерн?
4. **Мониторинг**: Нужны ли метрики и алерты или достаточно логов?
5. **CI/CD**: Запускать тесты автоматически или только локально?
6. **Типизация**: Строгий режим Pyright или warning-only?

---

## 📝 Следующие шаги

1. Обсудить приоритеты из списка выше
2. Согласовать подход к тестированию
3. Создать `logs/dev_diary.md` и начать вести записи
4. Настроить `pyproject.toml` с ruff/pyright
5. Написать первый unit-тест для `dice_check.py`

---

**Автор**: Cursor Agent  
**Версия**: 1.0  
**Последнее обновление**: 2026-02-15
