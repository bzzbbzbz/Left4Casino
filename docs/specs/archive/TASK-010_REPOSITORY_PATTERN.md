# TASK-010: Repository Pattern for Database

**ID**: TASK-010  
**Title**: Внедрение репозиторного паттерна для отделения БД от бизнес-логики  
**Priority**: MEDIUM  
**Status**: CODE_WRITTEN  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-010-1: Repository layer structure
Создать слой репозиториев для работы с БД.

**Acceptance Criteria:**
- Создана директория `telegram-casino-bot/bot/repositories/`
- Создан базовый класс `BaseRepository`
- Создан `UserRepository` для операций с пользователями
- Создан `EventRepository` для event_history
- Создан `ChallengeRepository` для dice challenges

### REQ-010-2: Abstraction from SQL
Инкапсулировать SQL-запросы внутри репозиториев.

**Acceptance Criteria:**
- Handlers НЕ содержат прямых SQL-запросов
- Handlers используют методы репозиториев: `user_repo.get_by_id()`
- SQL логика изолирована в repositories/
- Можно заменить БД без изменения handlers

### REQ-010-3: Dependency Injection
Внедрять репозитории через DI (middleware или фабрику).

**Acceptance Criteria:**
- Создан `RepositoryFactory` для создания репозиториев
- Repositories доступны в handlers через DI
- Не создаются глобальные singleton репозитории

### REQ-010-4: Testability
Упростить mock тестирование через интерфейсы.

**Acceptance Criteria:**
- Созданы Protocol/ABC интерфейсы для репозиториев
- В тестах можно подменить реальный репозиторий на mock
- Unit-тесты handlers не требуют реальной БД

---

## 🎯 Goals

**Primary Goal:**
Отделить бизнес-логику от деталей работы с БД для улучшения тестируемости и гибкости.

**Why This Matters:**
- **Maintainability**: SQL запросы в одном месте, легче рефакторить
- **Testability**: Можно mock репозитории и тестировать handlers без БД
- **Flexibility**: Можно заменить SQLite на PostgreSQL без изменения handlers
- **Single Responsibility**: Handlers занимаются бизнес-логикой, репозитории — данными

---

## 📐 Design

### Architecture Layers
```
┌─────────────────────────────────────┐
│   Handlers (Business Logic)         │  ← No SQL here!
│   /dice, /balance, /give            │
└──────────────┬──────────────────────┘
               │ uses
┌──────────────▼──────────────────────┐
│   Repositories (Data Access)        │  ← All SQL here
│   UserRepository, EventRepository   │
└──────────────┬──────────────────────┘
               │ uses
┌──────────────▼──────────────────────┐
│   Database (SQLite)                 │
│   aiosqlite connection              │
└─────────────────────────────────────┘
```

### Directory Structure
```
telegram-casino-bot/bot/
├── repositories/
│   ├── __init__.py
│   ├── base.py              # BaseRepository with common logic
│   ├── user.py              # UserRepository
│   ├── event.py             # EventRepository
│   ├── challenge.py         # ChallengeRepository
│   ├── debt.py              # DebtRepository
│   └── interfaces.py        # Protocol definitions for testing
├── handlers/
│   └── ...                  # Use repositories, not raw SQL
└── db.py                    # Low-level DB connection (used by repositories)
```

### Base Repository (repositories/base.py)
```python
"""Base repository with common functionality"""
from typing import Generic, TypeVar, Optional
import aiosqlite

T = TypeVar("T")

class BaseRepository(Generic[T]):
    """Base class for all repositories"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    async def _execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute query and return cursor"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor
    
    async def _fetchone(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        """Fetch single row"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchone()
    
    async def _fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Fetch all rows"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchall()
```

### User Repository (repositories/user.py)
```python
"""User repository for user-related database operations"""
from typing import Optional
from bot.repositories.base import BaseRepository
from bot.models.entities import User

class UserRepository(BaseRepository[User]):
    """Repository for user operations"""
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        row = await self._fetchone(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        if row:
            return User(**dict(row))
        return None
    
    async def get_balance(self, user_id: int) -> float:
        """Get user balance"""
        row = await self._fetchone(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        return row["balance"] if row else 0.0
    
    async def update_balance(self, user_id: int, new_balance: float) -> None:
        """Update user balance"""
        await self._execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id)
        )
    
    async def increment_balance(self, user_id: int, amount: float) -> float:
        """Increment balance atomically and return new value"""
        await self._execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id)
        )
        return await self.get_balance(user_id)
    
    async def transfer(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: float
    ) -> None:
        """Transfer money between users (atomic transaction)"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                # Deduct from sender
                await db.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                    (amount, from_user_id)
                )
                # Add to receiver
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (amount, to_user_id)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    
    async def get_safe_balance(self, user_id: int) -> float:
        """Get user's safe balance"""
        row = await self._fetchone(
            "SELECT safe_balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        return row["safe_balance"] if row else 0.0
    
    async def safe_deposit(self, user_id: int, amount: float) -> None:
        """Deposit to safe (atomic: balance → safe_balance)"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute(
                    """UPDATE users 
                       SET balance = balance - ?,
                           safe_balance = safe_balance + ?
                       WHERE user_id = ?""",
                    (amount, amount, user_id)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    
    async def safe_withdraw(self, user_id: int, amount: float) -> None:
        """Withdraw from safe (atomic: safe_balance → balance)"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN TRANSACTION")
            try:
                await db.execute(
                    """UPDATE users 
                       SET safe_balance = safe_balance - ?,
                           balance = balance + ?
                       WHERE user_id = ?""",
                    (amount, amount, user_id)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
```

### Event Repository (repositories/event.py)
```python
"""Event repository for event history operations"""
from bot.repositories.base import BaseRepository
from bot.models.events import GameEvent
import json

class EventRepository(BaseRepository[GameEvent]):
    """Repository for event history"""
    
    async def add(self, event: GameEvent) -> None:
        """Add event to history"""
        await self._execute(
            """INSERT INTO event_history 
               (event_id, user_id, event_type, amount, created_at, chat_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.user_id,
                event.event_type,
                event.amount,
                event.created_at.isoformat(),
                event.chat_id,
                json.dumps(event.metadata),
            ),
        )
    
    async def get_user_events(
        self,
        user_id: int,
        limit: int = 100
    ) -> list[GameEvent]:
        """Get recent events for user"""
        rows = await self._fetchall(
            """SELECT * FROM event_history 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (user_id, limit)
        )
        # Convert to GameEvent models
        return [self._row_to_event(dict(row)) for row in rows]
    
    def _row_to_event(self, row: dict) -> GameEvent:
        """Convert DB row to GameEvent"""
        from bot.models.events import create_event
        return create_event(
            event_type=row["event_type"],
            event_id=row["event_id"],
            user_id=row["user_id"],
            amount=row["amount"],
            chat_id=row["chat_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
```

### Repository Factory (repositories/__init__.py)
```python
"""Repository factory for dependency injection"""
from bot.repositories.user import UserRepository
from bot.repositories.event import EventRepository
from bot.repositories.challenge import ChallengeRepository
from bot.repositories.debt import DebtRepository

class RepositoryFactory:
    """Factory for creating repositories with shared DB connection"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def create_user_repo(self) -> UserRepository:
        return UserRepository(self.db_path)
    
    def create_event_repo(self) -> EventRepository:
        return EventRepository(self.db_path)
    
    def create_challenge_repo(self) -> ChallengeRepository:
        return ChallengeRepository(self.db_path)
    
    def create_debt_repo(self) -> DebtRepository:
        return DebtRepository(self.db_path)
```

### Protocol Interfaces (repositories/interfaces.py)
```python
"""Protocol interfaces for testing"""
from typing import Protocol, Optional
from bot.models.entities import User
from bot.models.events import GameEvent

class IUserRepository(Protocol):
    """Interface for user repository (for mocking)"""
    
    async def get_by_id(self, user_id: int) -> Optional[User]: ...
    async def get_balance(self, user_id: int) -> float: ...
    async def update_balance(self, user_id: int, new_balance: float) -> None: ...
    async def transfer(self, from_user_id: int, to_user_id: int, amount: float) -> None: ...

class IEventRepository(Protocol):
    """Interface for event repository"""
    
    async def add(self, event: GameEvent) -> None: ...
    async def get_user_events(self, user_id: int, limit: int) -> list[GameEvent]: ...
```

### Usage in Handlers (Example)
```python
# bot/handlers/transfer.py
from aiogram import Router, F
from aiogram.filters import Command
from bot.repositories import RepositoryFactory

router = Router()

# Inject repository factory via middleware
@router.message(Command("give"))
async def cmd_give(
    message: types.Message,
    repo_factory: RepositoryFactory  # ← Injected
):
    # Parse command
    args = message.text.split()
    amount = int(args[1])
    recipient_id = extract_user_id(args[2])
    
    # Use repositories (no SQL!)
    user_repo = repo_factory.create_user_repo()
    event_repo = repo_factory.create_event_repo()
    
    # Business logic
    sender_id = message.from_user.id
    sender_balance = await user_repo.get_balance(sender_id)
    
    if sender_balance < amount:
        await message.reply("Недостаточно очков")
        return
    
    # Transfer
    await user_repo.transfer(sender_id, recipient_id, amount)
    
    # Log event
    event = TransferEvent(
        event_id=str(uuid.uuid4()),
        user_id=sender_id,
        amount=amount,
        metadata={"to_user_id": recipient_id}
    )
    await event_repo.add(event)
    
    await message.reply(f"Переведено {amount} очков")
```

---

## ✅ Implementation Checklist

### Phase 1: Repository Structure
- [x] Создать `repositories/` директорию
- [x] Создать `base.py` с `BaseRepository`
- [x] Создать `interfaces.py` с Protocol definitions

### Phase 2: Core Repositories
- [x] Создать `UserRepository` с методами из `db.py`
- [x] Создать `EventRepository`
- [x] Создать `ChallengeRepository`
- [x] Создать `DebtRepository`

### Phase 3: Factory & DI
- [x] Создать `RepositoryFactory`
- [x] Настроить DI через aiogram dependency (repo_factory в Dispatcher)
- [x] Обновить handlers для использования репозиториев

### Phase 4: Migration
- [x] Мигрировать `handlers/transfer.py`
- [x] Мигрировать `handlers/dice_fight.py`
- [x] Мигрировать `handlers/safe.py`
- [ ] Удалить дублирующийся код из `db.py` (оставлен для остальных handlers/services)

### Phase 5: Testing
- [ ] Написать unit-тесты для репозиториев
- [ ] Написать mock тесты для handlers (using Protocol)
- [ ] Убедиться, что handlers работают без реальной БД в тестах

---

## 🧪 Testing & Validation

### Unit Tests for Repository
```python
# tests/unit/test_user_repository.py
import pytest
from bot.repositories.user import UserRepository

@pytest.mark.asyncio
async def test_get_balance(test_db_path):
    repo = UserRepository(test_db_path)
    # Setup: create user with balance 100
    await repo.update_balance(123, 100.0)
    
    # Act
    balance = await repo.get_balance(123)
    
    # Assert
    assert balance == 100.0
```

### Mock Tests for Handlers
```python
# tests/unit/test_transfer_handler.py
import pytest
from unittest.mock import AsyncMock
from bot.handlers.transfer import cmd_give

@pytest.mark.asyncio
async def test_transfer_insufficient_balance(mock_message):
    # Arrange: Mock repository
    mock_user_repo = AsyncMock()
    mock_user_repo.get_balance.return_value = 10  # Not enough
    
    mock_repo_factory = AsyncMock()
    mock_repo_factory.create_user_repo.return_value = mock_user_repo
    
    # Act
    await cmd_give(mock_message, mock_repo_factory)
    
    # Assert
    mock_message.reply.assert_called_with("Недостаточно очков")
    mock_user_repo.transfer.assert_not_called()  # Transfer not executed
```

### Success Metrics
- Handlers не содержат SQL-запросов
- Можно протестировать handlers с mock репозиториями
- Репозитории имеют 100% coverage

---

## 📦 Dependencies

**Before this task:**
- `bot/db.py` содержит все SQL-запросы
- Handlers используют `db` напрямую

**After this task:**
- Handlers используют репозитории
- `db.py` может быть упрощён или удалён

**Depends on:**
- TASK-005 (Pydantic Models) — рекомендуется для типизации

---

## 📝 Notes

### Repository Pattern Benefits
```
Before:
Handler → SQL query → Database
↑ Tightly coupled, hard to test

After:
Handler → Repository → Database
↑ Loose coupling, easy to mock
```

### When to Use?
- **Use**: Если handlers имеют сложные SQL-запросы
- **Use**: Если планируется смена БД (SQLite → PostgreSQL)
- **Skip**: Если проект очень маленький (< 5 таблиц, < 10 запросов)

### Protocol vs ABC
```python
# Protocol (structural typing)
class IUserRepository(Protocol):
    async def get_balance(self, user_id: int) -> float: ...

# ABC (nominal typing)
class IUserRepository(ABC):
    @abstractmethod
    async def get_balance(self, user_id: int) -> float: ...
```
Protocol проще для testing (duck typing).

### DI via Middleware
```python
# bot/middlewares/repository.py
class RepositoryMiddleware(BaseMiddleware):
    def __init__(self, db_path: str):
        self.factory = RepositoryFactory(db_path)
    
    async def __call__(self, handler, event, data):
        data["repo_factory"] = self.factory
        return await handler(event, data)
```

---

## 🔗 References

- Repository Pattern: https://martinfowler.com/eaaCatalog/repository.html
- Python Protocols: https://peps.python.org/pep-0544/
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 10)
- `@bot/db.py` (current implementation)
