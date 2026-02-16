# TASK-006: Test Structure Organization

**ID**: TASK-006  
**Title**: Разделение unit и integration тестов  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-006-1: Directory structure
Создать полную структуру тестовых директорий.

**Acceptance Criteria:**
- Создана `tests/unit/` для unit-тестов (быстрые, без БД/сети)
- Создана `tests/integration/` для интеграционных тестов (с БД, полные флоу)
- Создана `tests/fixtures/` для общих фикстур и моков
- Все директории содержат `__init__.py`

### REQ-006-2: Conftest organization
Организовать фикстуры по назначению.

**Acceptance Criteria:**
- `tests/conftest.py` — глобальные фикстуры (event loop, базовые настройки)
- `tests/unit/conftest.py` — фикстуры для unit-тестов (моки БД, сервисов)
- `tests/integration/conftest.py` — фикстуры для integration (реальная БД, бот)
- Фикстуры не дублируются

### REQ-006-3: Integration tests setup
Создать базовые интеграционные тесты.

**Acceptance Criteria:**
- `tests/integration/test_handlers.py` — тесты команд бота end-to-end
- `tests/integration/test_db.py` — тесты работы с реальной БД
- Используется in-memory SQLite для скорости
- Тесты очищают БД после каждого запуска

### REQ-006-4: Pytest configuration
Настроить pytest markers для разделения типов тестов.

**Acceptance Criteria:**
- В `pyproject.toml` добавлены markers: `unit`, `integration`, `slow`
- Можно запустить только unit: `pytest -m unit`
- Можно запустить только integration: `pytest -m integration`
- По умолчанию запускаются все тесты

---

## 🎯 Goals

**Primary Goal:**
Разделить быстрые unit-тесты (запускаются при каждом изменении) и медленные integration-тесты (запускаются перед коммитом) для оптимизации developer workflow.

**Why This Matters:**
- **Fast Feedback**: Unit-тесты завершаются за < 5 секунд, можно запускать после каждого изменения
- **Comprehensive Coverage**: Integration-тесты проверяют взаимодействие компонентов
- **CI Optimization**: В CI можно запускать unit-тесты на каждый commit, integration — только на PR
- **Clear Separation**: Понятно, где искать тест для конкретной функции

---

## 📐 Design

### Directory Structure
```
tests/
├── __init__.py
├── conftest.py                   # Global fixtures
├── pytest.ini                    # Pytest config (optional, can use pyproject.toml)
├── fixtures/
│   ├── __init__.py
│   ├── mock_bot.py               # Mock aiogram bot
│   ├── mock_db.py                # Mock database
│   └── sample_data.py            # Test data fixtures
├── unit/
│   ├── __init__.py
│   ├── conftest.py               # Unit test fixtures
│   ├── test_dice_check.py        # From TASK-004
│   ├── test_heist_economy.py     # From TASK-004
│   ├── test_ai_client.py         # AI service logic
│   └── test_models.py            # Pydantic models validation
└── integration/
    ├── __init__.py
    ├── conftest.py               # Integration fixtures
    ├── test_handlers.py          # Full command flows
    ├── test_db.py                # Database operations
    └── test_heist_flow.py        # Complete heist scenario
```

### Pytest Markers Configuration
```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "unit: Fast unit tests without external dependencies",
    "integration: Integration tests with database and bot",
    "slow: Slow tests that take > 1 second",
]
```

### Global Fixtures (tests/conftest.py)
```python
"""Global test fixtures"""
import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def test_config():
    """Test configuration"""
    return {
        "db_path": ":memory:",  # In-memory SQLite for tests
        "bot_token": "123456:TEST_TOKEN",
        "openrouter_api_key": "test_key",
    }
```

### Unit Test Fixtures (tests/unit/conftest.py)
```python
"""Fixtures for unit tests"""
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_db():
    """Mock database for unit tests"""
    mock = AsyncMock()
    mock.get_balance.return_value = 100
    mock.update_balance.return_value = None
    return mock

@pytest.fixture
def mock_bot():
    """Mock aiogram bot"""
    mock = MagicMock()
    mock.send_message = AsyncMock()
    return mock

@pytest.fixture
def mock_ai_client():
    """Mock AI client"""
    mock = AsyncMock()
    mock.generate_response.return_value = {
        "content": "Test response",
        "completion_data": {"done": True, "score": 10}
    }
    return mock
```

### Integration Test Fixtures (tests/integration/conftest.py)
```python
"""Fixtures for integration tests"""
import pytest
import aiosqlite
import tempfile
import os
from telegram-casino-bot.bot.db import Database

@pytest.fixture
async def test_db():
    """Create temporary test database"""
    # Use temp file for isolation (or :memory:)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_file.close()
    
    db = Database(db_path=temp_file.name)
    await db.init_db()  # Create tables
    
    yield db
    
    # Cleanup
    os.unlink(temp_file.name)

@pytest.fixture
async def test_user(test_db):
    """Create test user in database"""
    user_id = 123456
    await test_db.ensure_user_exists(user_id)
    return user_id

@pytest.fixture
def mock_telegram_message():
    """Create mock Telegram message object"""
    from unittest.mock import MagicMock
    
    message = MagicMock()
    message.from_user.id = 123456
    message.chat.id = -1001234567890
    message.text = "/start"
    message.reply = AsyncMock()
    return message
```

### Integration Test Examples

#### test_handlers.py
```python
"""Integration tests for bot handlers"""
import pytest
from telegram-casino-bot.bot.handlers.default_commands import cmd_start, cmd_balance

@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_command_creates_user(test_db, mock_telegram_message):
    """Test /start command creates user in database"""
    # Act
    await cmd_start(mock_telegram_message, test_db)
    
    # Assert
    user = await test_db.get_user(mock_telegram_message.from_user.id)
    assert user.balance == 50  # starting_points
    assert mock_telegram_message.reply.called

@pytest.mark.integration
@pytest.mark.asyncio
async def test_balance_command_shows_correct_balance(test_db, mock_telegram_message):
    """Test /balance command shows user's balance"""
    # Arrange
    user_id = mock_telegram_message.from_user.id
    await test_db.ensure_user_exists(user_id)
    await test_db.update_balance(user_id, 100)
    
    # Act
    await cmd_balance(mock_telegram_message, test_db)
    
    # Assert
    reply_text = mock_telegram_message.reply.call_args[0][0]
    assert "100" in reply_text
```

#### test_db.py
```python
"""Integration tests for database operations"""
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_transfer_money_atomic_transaction(test_db):
    """Test transfer is atomic - both users updated or neither"""
    sender_id = 111
    receiver_id = 222
    amount = 50
    
    # Setup
    await test_db.ensure_user_exists(sender_id)
    await test_db.ensure_user_exists(receiver_id)
    await test_db.update_balance(sender_id, 100)
    await test_db.update_balance(receiver_id, 50)
    
    # Act
    await test_db.transfer_money(
        from_user_id=sender_id,
        to_user_id=receiver_id,
        amount=amount
    )
    
    # Assert
    sender_balance = await test_db.get_balance(sender_id)
    receiver_balance = await test_db.get_balance(receiver_id)
    assert sender_balance == 50
    assert receiver_balance == 100
```

---

## ✅ Implementation Checklist

### Phase 1: Structure
- [ ] Создать полную структуру директорий
- [ ] Создать все `__init__.py` файлы
- [ ] Переместить существующие тесты в `tests/unit/`

### Phase 2: Fixtures
- [ ] Создать `tests/conftest.py` с глобальными фикстурами
- [ ] Создать `tests/unit/conftest.py` с моками
- [ ] Создать `tests/integration/conftest.py` с реальными объектами
- [ ] Создать `tests/fixtures/` с переиспользуемыми данными

### Phase 3: Pytest Config
- [ ] Добавить markers в `pyproject.toml`
- [ ] Настроить testpaths
- [ ] Документировать команды запуска

### Phase 4: Integration Tests
- [ ] Создать `test_handlers.py` с 2-3 базовыми тестами
- [ ] Создать `test_db.py` с тестами транзакций
- [ ] Создать `test_heist_flow.py` (опционально)

### Phase 5: Documentation
- [ ] Обновить `AGENTS.md` с командами запуска тестов
- [ ] Документировать markers и их назначение
- [ ] Добавить примеры использования фикстур

---

## 🧪 Testing & Validation

### Run Commands
```bash
# Все тесты
pytest tests/

# Только unit (быстро)
pytest -m unit

# Только integration (медленно)
pytest -m integration

# Исключить slow тесты
pytest -m "not slow"

# С verbose и coverage
pytest tests/ -v --cov=telegram-casino-bot/bot
```

### Performance Benchmark
```bash
# Unit tests should be < 5 seconds
time pytest tests/unit/

# Integration tests can be < 30 seconds
time pytest tests/integration/
```

### Success Metrics
- Unit-тесты завершаются за < 5 секунд
- Integration-тесты завершаются за < 30 секунд
- Все тесты проходят (зелёные)
- Понятно, в какую директорию добавлять новый тест

---

## 📦 Dependencies

**Before this task:**
- TASK-004 (базовые unit-тесты) — будут перемещены в правильную структуру

**After this task:**
- Используется в CI/CD (TASK-012) — разные jobs для unit и integration
- Упрощает добавление новых тестов

---

## 📝 Notes

### When to Write Unit vs Integration Test

**Unit Test** (tests/unit/):
- Тестирует одну функцию/метод изолированно
- Использует моки для зависимостей (БД, API, bot)
- Быстрый (< 100ms на тест)
- Примеры: `test_dice_check.py`, `test_heist_economy.py`

**Integration Test** (tests/integration/):
- Тестирует взаимодействие компонентов
- Использует реальные объекты (БД, может быть mock bot)
- Медленнее (100ms - 1s на тест)
- Примеры: `test_handlers.py`, `test_db.py`

### In-Memory SQLite for Speed
```python
# Fast in-memory database
db = Database(db_path=":memory:")

# Or use temp file for persistence during test
import tempfile
temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
db = Database(db_path=temp_file.name)
```

### Pytest Markers in Code
```python
@pytest.mark.unit
def test_fast_function():
    pass

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_flow():
    pass

@pytest.mark.slow
@pytest.mark.integration
async def test_long_running_scenario():
    pass
```

### CI Configuration (Future)
```yaml
# .github/workflows/test.yml
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -m unit
  
  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -m integration
```

---

## 🔗 References

- Pytest fixtures: https://docs.pytest.org/en/stable/fixture.html
- Pytest markers: https://docs.pytest.org/en/stable/example/markers.html
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 6)
- `@TASK-004_UNIT_TESTS.md` (базовые тесты)
