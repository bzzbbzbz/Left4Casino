# TASK-005: Pydantic Models Implementation

**ID**: TASK-005  
**Title**: Типизация событий и конфигов через Pydantic  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-005-1: Events models
Создать Pydantic модели для игровых событий.

**Acceptance Criteria:**
- Создан файл `telegram-casino-bot/bot/models/events.py`
- Содержит базовую модель `GameEvent`
- Содержит специализированные модели для каждого типа события
- Все поля типизированы и валидируются
- Модели используются при записи в `event_history`

### REQ-005-2: Config models
Создать Pydantic модели для конфигурации бота.

**Acceptance Criteria:**
- Создан файл `telegram-casino-bot/bot/models/config.py`
- Содержит модель `BotConfig` для секции `[bot]`
- Содержит модель `GameConfig` для секции `[game_config]`
- Содержит модель `HeistConfig` для секции `[heist]`
- Все переменные окружения валидируются при старте бота

### REQ-005-3: Database models (optional)
Создать Pydantic модели для данных из БД.

**Acceptance Criteria:**
- Создан файл `telegram-casino-bot/bot/models/entities.py`
- Содержит модель `User` для таблицы `users`
- Содержит модель `DiceChallenge` для таблицы `dice_challenges`
- Модели используются как return types в методах БД

### REQ-005-4: Integration with existing code
Интегрировать модели в существующий код.

**Acceptance Criteria:**
- `bot/db.py` методы возвращают Pydantic модели вместо dict
- `bot/services/ai.py` использует модели для структуры ответов
- `bot/handlers/` используют модели для валидации входных данных
- Нет breaking changes — все работает как раньше

---

## 🎯 Goals

**Primary Goal:**
Добавить статическую типизацию и runtime-валидацию данных для предотвращения багов и улучшения developer experience.

**Why This Matters:**
- **Runtime Validation**: Pydantic проверяет данные при создании объекта (например, `amount > 0`)
- **Type Safety**: IDE и Cursor видят типы полей и предлагают автодополнение
- **Documentation**: Модели самодокументируются через типы и docstrings
- **AI-friendly**: Cursor использует типы для генерации корректного кода

---

## 📐 Design

### models/events.py
```python
"""Pydantic models for game events"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, validator

class GameEvent(BaseModel):
    """Base model for all game events"""
    event_id: str = Field(..., description="Unique event ID (UUID)")
    user_id: int = Field(..., gt=0, description="Telegram user ID")
    event_type: str = Field(..., description="Type of event")
    amount: int = Field(..., description="Amount of points (can be negative)")
    created_at: datetime = Field(default_factory=datetime.now)
    chat_id: Optional[int] = Field(None, description="Chat ID where event occurred")
    metadata: dict = Field(default_factory=dict, description="Additional event data")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class WinEvent(GameEvent):
    """Player won in slots"""
    event_type: Literal["win"] = "win"
    amount: int = Field(..., gt=0, description="Win amount (positive)")
    
    @validator("metadata")
    def validate_win_metadata(cls, v):
        """Ensure win events have required metadata"""
        required_keys = ["base_score", "bid", "jackpot_multiplier"]
        if not all(k in v for k in required_keys):
            raise ValueError(f"Win event must have metadata: {required_keys}")
        return v

class LossEvent(GameEvent):
    """Player lost in slots"""
    event_type: Literal["loss"] = "loss"
    amount: int = Field(..., lt=0, description="Loss amount (negative)")

class TransferEvent(GameEvent):
    """Player transferred points to another player"""
    event_type: Literal["transfer"] = "transfer"
    amount: int = Field(..., gt=0, description="Transfer amount")
    
    @validator("metadata")
    def validate_transfer_metadata(cls, v):
        """Ensure transfer has recipient"""
        if "to_user_id" not in v:
            raise ValueError("Transfer event must have 'to_user_id' in metadata")
        return v

class HeistContributionEvent(GameEvent):
    """Player contributed to heist pot"""
    event_type: Literal["heist_contribution"] = "heist_contribution"
    amount: int = Field(..., gt=0, description="Contribution amount")
    
    @validator("metadata")
    def validate_heist_metadata(cls, v):
        """Ensure heist events have pot info"""
        if "pot_after" not in v:
            raise ValueError("Heist event must have 'pot_after'")
        return v

class HappyMomentWinEvent(GameEvent):
    """Player won during happy moment"""
    event_type: Literal["happy_moment_win"] = "happy_moment_win"
    amount: int = Field(..., gt=0)
    
    @validator("metadata")
    def validate_happy_moment_metadata(cls, v):
        """Ensure happy moment wins have multiplier"""
        if "happy_moment_multiplier" not in v:
            raise ValueError("Happy moment event must have multiplier")
        return v

# Factory function
def create_event(event_type: str, **kwargs) -> GameEvent:
    """Create appropriate event model based on type"""
    event_map = {
        "win": WinEvent,
        "loss": LossEvent,
        "transfer": TransferEvent,
        "heist_contribution": HeistContributionEvent,
        "happy_moment_win": HappyMomentWinEvent,
    }
    model_class = event_map.get(event_type, GameEvent)
    return model_class(event_type=event_type, **kwargs)
```

### models/config.py
```python
"""Pydantic models for bot configuration"""
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings

class BotConfig(BaseSettings):
    """Bot configuration from settings.toml [bot] section"""
    token: str = Field(..., description="Telegram bot token")
    fsm_mode: str = Field(default="redis", description="FSM storage mode")
    
    @validator("fsm_mode")
    def validate_fsm_mode(cls, v):
        if v not in ("redis", "memory"):
            raise ValueError("fsm_mode must be 'redis' or 'memory'")
        return v
    
    class Config:
        env_prefix = "BOT_"

class GameConfig(BaseModel):
    """Game configuration from settings.toml [game_config]"""
    starting_points: int = Field(default=50, ge=0)
    throttle_time_spin: int = Field(default=2, ge=0, le=10)
    throttle_time_other: int = Field(default=1, ge=0, le=10)
    throttle_time_top: int = Field(default=5, ge=0, le=30)
    
    @validator("starting_points")
    def validate_starting_points(cls, v):
        if v < 0:
            raise ValueError("starting_points must be non-negative")
        return v

class HeistConfig(BaseModel):
    """Heist configuration from settings.toml [heist]"""
    enabled: bool = Field(default=True)
    pot_cap_multiplier: float = Field(default=0.05, gt=0, le=1.0)
    min_pot_multiplier: float = Field(default=0.01, gt=0, le=1.0)
    commission_pct: int = Field(default=10, ge=0, le=50)
    phase1_min_duration: int = Field(default=10, ge=5)
    phase1_max_duration: int = Field(default=25, le=30)
    phase2_min_duration: int = Field(default=2, ge=1)
    phase2_max_duration: int = Field(default=5, le=10)
    
    @validator("commission_pct")
    def validate_commission(cls, v):
        """Комиссия не должна быть больше 50%"""
        if v > 50:
            raise ValueError("commission_pct cannot exceed 50%")
        return v

class AppConfig(BaseModel):
    """Root configuration combining all sections"""
    bot: BotConfig
    game: GameConfig
    heist: HeistConfig
    # Add other sections as needed
```

### models/entities.py
```python
"""Pydantic models for database entities"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field

class User(BaseModel):
    """User entity from database"""
    user_id: int = Field(..., gt=0)
    balance: float = Field(default=50.0)
    safe_balance: float = Field(default=0.0, ge=0.0)
    bid: int = Field(default=1, ge=1)
    state: Literal["IDLE", "IN_DIALOGUE"] = "IDLE"
    nickname: Optional[str] = None
    slots_played: int = Field(default=0, ge=0)
    slots_won: int = Field(default=0, ge=0)
    dice_challenges_won: int = Field(default=0, ge=0)
    dice_challenges_lost: int = Field(default=0, ge=0)
    dice_challenges_draw: int = Field(default=0, ge=0)
    bankruptcy_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        orm_mode = True  # Allow creation from DB rows

class DiceChallenge(BaseModel):
    """Dice challenge entity"""
    challenge_id: int
    challenger_id: int
    opponent_id: Optional[int] = None
    bet_amount: int = Field(..., gt=0)
    chat_id: int
    status: Literal["pending", "accepted", "completed", "expired"]
    challenger_roll: Optional[int] = Field(None, ge=1, le=6)
    opponent_roll: Optional[int] = Field(None, ge=1, le=6)
    created_at: datetime
    expires_at: datetime
    
    class Config:
        orm_mode = True
```

### Integration Example
```python
# bot/db.py
from bot.models.entities import User
from bot.models.events import create_event

class Database:
    async def get_user(self, user_id: int) -> User:
        """Get user from DB, return Pydantic model"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return User(**dict(row))
            # Return default user
            return User(user_id=user_id)
    
    async def add_event(self, event: GameEvent) -> None:
        """Add event to history, accepting Pydantic model"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
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
            await db.commit()

# Usage in handlers
from bot.models.events import create_event

async def handle_win(user_id: int, amount: int, metadata: dict):
    event = create_event(
        event_type="win",
        event_id=str(uuid.uuid4()),
        user_id=user_id,
        amount=amount,
        metadata=metadata,
    )
    # Validation happens automatically here
    await db.add_event(event)
```

---

## ✅ Implementation Checklist

### Phase 1: Structure
- [ ] Создать `telegram-casino-bot/bot/models/__init__.py`
- [ ] Установить `pydantic>=2.0`, `pydantic-settings>=2.0`

### Phase 2: Events Models
- [ ] Создать `models/events.py` с базовой моделью `GameEvent`
- [ ] Добавить специализированные модели: Win, Loss, Transfer, Heist, HappyMoment
- [ ] Добавить factory function `create_event()`
- [ ] Написать unit-тесты для валидации (optional)

### Phase 3: Config Models
- [ ] Создать `models/config.py` с моделями конфигов
- [ ] Интегрировать с `bot/config_reader.py`
- [ ] Протестировать загрузку конфига при старте бота

### Phase 4: Entity Models
- [ ] Создать `models/entities.py` с моделями БД
- [ ] Обновить `bot/db.py` для возврата Pydantic моделей
- [ ] Обновить handlers для работы с моделями

### Phase 5: Testing & Validation
- [ ] Запустить бота — не должно быть ошибок валидации
- [ ] Создать event с невалидными данными — должна быть ошибка
- [ ] Проверить автодополнение в Cursor — должны быть подсказки полей

---

## 🧪 Testing & Validation

### Unit Tests for Models
```python
# tests/unit/test_models.py
import pytest
from pydantic import ValidationError
from bot.models.events import WinEvent, create_event

def test_win_event_requires_positive_amount():
    """Win event should validate amount > 0"""
    with pytest.raises(ValidationError):
        WinEvent(
            event_id="test",
            user_id=123,
            amount=-10,  # Should fail
            metadata={"base_score": 7, "bid": 1, "jackpot_multiplier": 1},
        )

def test_win_event_requires_metadata():
    """Win event should require specific metadata keys"""
    with pytest.raises(ValidationError):
        WinEvent(
            event_id="test",
            user_id=123,
            amount=10,
            metadata={},  # Missing required keys
        )

def test_create_event_factory():
    """Factory should create correct event type"""
    event = create_event(
        event_type="win",
        event_id="test",
        user_id=123,
        amount=10,
        metadata={"base_score": 7, "bid": 1, "jackpot_multiplier": 1},
    )
    assert isinstance(event, WinEvent)
```

### Manual Testing
1. Запустить бота с валидным конфигом — должен стартовать
2. Запустить с невалидным конфигом (например, `commission_pct=60`) — ошибка валидации
3. Создать event с отрицательным amount для WinEvent — ошибка
4. Проверить автодополнение: `user.` → должны быть подсказки полей

### Success Metrics
- Все существующие функции работают как раньше
- Cursor предлагает автодополнение для полей моделей
- Runtime ошибки валидации ловятся до записи в БД

---

## 📦 Dependencies

**Before this task:**
- Существующий код работает (можно добавлять модели постепенно)

**After this task:**
- Используется в handlers и services
- Используется в тестах (TASK-004)
- Улучшает type checking (TASK-003)

---

## 📝 Notes

### Pydantic v2 vs v1
- Проект должен использовать Pydantic v2 (быстрее, лучше типизация)
- Если в зависимостях есть библиотеки с Pydantic v1 — могут быть конфликты

### Incremental Adoption
Не обязательно мигрировать весь код сразу:
1. Начните с events (самое критичное)
2. Затем config (валидация при старте)
3. Затем entities (улучшение типизации БД)

### Performance
- Pydantic v2 очень быстрый (Rust core)
- Валидация добавляет ~5-10 мкс на объект (незаметно)

### JSON Serialization
```python
# Pydantic models легко сериализуются
event = WinEvent(...)
event.model_dump()  # → dict
event.model_dump_json()  # → JSON string
```

---

## 🔗 References

- Pydantic docs: https://docs.pydantic.dev/
- Pydantic Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 5)
- `@bot/db.py` (интеграция)
