# TASK-007: Database Migrations System

**ID**: TASK-007  
**Title**: Внедрение системы миграций БД (Alembic или SQL-скрипты)  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-007-1: Migration system choice
Выбрать подход к миграциям: Alembic (автоматизация) или SQL-скрипты (контроль).

**Acceptance Criteria:**
- Проведён анализ плюсов/минусов каждого подхода
- Выбран подход согласованный с командой
- Задокументирована причина выбора в dev_diary.md

### REQ-007-2: Migration infrastructure
Настроить инфраструктуру для миграций.

**Acceptance Criteria (Alembic):**
- Установлен `alembic>=1.13.0`
- Создана структура `alembic/` с env.py и script.py.mako
- Настроен `alembic.ini` для работы с aiosqlite
- Команда `alembic upgrade head` работает

**Acceptance Criteria (SQL Scripts):**
- Создана структура `migrations/` с версионными SQL-файлами
- Создан `migrations/migration_runner.py` для применения миграций
- Создана таблица `schema_versions` для отслеживания версии
- Команда `python migrations/migration_runner.py` работает

### REQ-007-3: Baseline migration
Создать baseline миграцию с текущей схемой БД.

**Acceptance Criteria:**
- Создана миграция `001_initial_schema` с полной схемой
- Миграция содержит все таблицы: users, event_history, ai_credit_sessions, и т.д.
- Применение миграции на пустую БД создаёт рабочую схему
- Rollback (downgrade) корректно удаляет таблицы

### REQ-007-4: Documentation and workflow
Документировать процесс создания и применения миграций.

**Acceptance Criteria:**
- В `AGENTS.md` добавлена секция "Database Migrations"
- Документированы команды: создание, применение, откат миграций
- Добавлены примеры миграций (добавить колонку, создать индекс)
- Описан workflow при изменении схемы

---

## 🎯 Goals

**Primary Goal:**
Внедрить версионирование схемы БД для безопасного применения изменений и возможности отката при проблемах.

**Why This Matters:**
- **Production Safety**: Можно откатить миграцию если что-то пошло не так
- **History**: Видно, кто, когда и зачем изменил схему
- **Automation**: Миграции применяются автоматически при деплое
- **Team Collaboration**: Несколько разработчиков могут работать с БД без конфликтов

---

## 📐 Design

### Approach Comparison

| Критерий | Alembic | SQL Scripts |
|----------|---------|-------------|
| **Автогенерация** | ✅ Автоматически генерирует миграции из моделей | ❌ Ручное написание SQL |
| **Контроль** | ⚠️ Может генерировать лишнее | ✅ Полный контроль над SQL |
| **Сложность** | ⚠️ Требует изучения Alembic API | ✅ Простой SQL |
| **Rollback** | ✅ Встроенный downgrade | ⚠️ Нужно писать вручную |
| **Dependency** | ⚠️ Ещё одна зависимость | ✅ Нет внешних зависимостей |
| **Best for** | Проекты с частыми изменениями схемы | Проекты с редкими изменениями |

**Recommendation**: **SQL Scripts** для этого проекта, т.к.:
1. Схема БД относительно стабильна (7 таблиц)
2. Нет ORM (SQLAlchemy), с которым Alembic интегрируется
3. Полный контроль над миграциями критичен для game economy
4. Простота важнее автоматизации

### Directory Structure (SQL Scripts Approach)
```
migrations/
├── README.md                    # Инструкции
├── migration_runner.py          # Скрипт применения миграций
├── 001_initial_schema.sql       # Baseline: все таблицы
├── 002_add_heist_tables.sql     # Добавлены heist-таблицы
├── 003_add_safe_balance.sql     # Добавлена колонка safe_balance
└── template.sql                 # Шаблон для новых миграций
```

### Migration Format
```sql
-- migrations/003_add_safe_balance.sql
-- Migration: Add safe_balance column to users table
-- Author: cursor-agent
-- Date: 2026-01-20
-- Reason: Implement safe feature (SAFE_SPEC.md)

-- ============================================================
-- UPGRADE
-- ============================================================

ALTER TABLE users ADD COLUMN safe_balance REAL DEFAULT 0.0 NOT NULL;

-- Update existing users to have 0 safe_balance
UPDATE users SET safe_balance = 0.0 WHERE safe_balance IS NULL;

-- ============================================================
-- DOWNGRADE (optional, for rollback)
-- ============================================================

-- To rollback:
-- ALTER TABLE users DROP COLUMN safe_balance;
```

### Migration Runner (migrations/migration_runner.py)
```python
"""Database migration runner"""
import aiosqlite
import asyncio
import os
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent
DB_PATH = "telegram-casino-bot/bot/casino.db"

async def init_schema_versions_table(db: aiosqlite.Connection):
    """Create schema_versions table if not exists"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
    """)
    await db.commit()

async def get_current_version(db: aiosqlite.Connection) -> int:
    """Get current schema version"""
    cursor = await db.execute(
        "SELECT MAX(version) FROM schema_versions"
    )
    result = await cursor.fetchone()
    return result[0] if result[0] else 0

async def apply_migration(db: aiosqlite.Connection, migration_file: Path):
    """Apply single migration file"""
    version = int(migration_file.stem.split("_")[0])
    
    print(f"Applying migration {version}: {migration_file.name}")
    
    # Read and execute migration SQL
    sql = migration_file.read_text()
    # Extract only UPGRADE section
    upgrade_sql = sql.split("-- UPGRADE")[1].split("-- DOWNGRADE")[0]
    
    await db.executescript(upgrade_sql)
    
    # Record migration
    await db.execute(
        """INSERT INTO schema_versions (version, applied_at, description)
           VALUES (?, datetime('now'), ?)""",
        (version, migration_file.name)
    )
    await db.commit()
    print(f"✓ Migration {version} applied successfully")

async def run_migrations():
    """Run all pending migrations"""
    async with aiosqlite.connect(DB_PATH) as db:
        await init_schema_versions_table(db)
        current_version = await get_current_version(db)
        
        print(f"Current schema version: {current_version}")
        
        # Find pending migrations
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        migration_files = [
            f for f in migration_files
            if f.stem.split("_")[0].isdigit() and 
               int(f.stem.split("_")[0]) > current_version
        ]
        
        if not migration_files:
            print("No pending migrations")
            return
        
        print(f"Found {len(migration_files)} pending migration(s)")
        
        for migration_file in migration_files:
            await apply_migration(db, migration_file)
        
        new_version = await get_current_version(db)
        print(f"\n✓ All migrations applied! New version: {new_version}")

if __name__ == "__main__":
    asyncio.run(run_migrations())
```

### Baseline Migration (001_initial_schema.sql)
```sql
-- migrations/001_initial_schema.sql
-- Migration: Initial database schema
-- Author: cursor-agent
-- Date: 2026-02-15
-- Reason: Baseline migration from existing schema

-- ============================================================
-- UPGRADE
-- ============================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 50.0,
    safe_balance REAL DEFAULT 0.0,
    bid INTEGER DEFAULT 1,
    state TEXT DEFAULT 'IDLE',
    nickname TEXT,
    slots_played INTEGER DEFAULT 0,
    slots_won INTEGER DEFAULT 0,
    dice_challenges_won INTEGER DEFAULT 0,
    dice_challenges_lost INTEGER DEFAULT 0,
    dice_challenges_draw INTEGER DEFAULT 0,
    bankruptcy_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Event history
CREATE TABLE IF NOT EXISTS event_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    chat_id INTEGER,
    metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- AI credit sessions
CREATE TABLE IF NOT EXISTS ai_credit_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_type TEXT,
    task_details TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now')),
    closed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- AI dialogue messages
CREATE TABLE IF NOT EXISTS ai_dialogue_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES ai_credit_sessions(session_id)
);

-- User groups
CREATE TABLE IF NOT EXISTS user_groups (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    last_active TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, chat_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Dice challenges
CREATE TABLE IF NOT EXISTS dice_challenges (
    challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id INTEGER NOT NULL,
    opponent_id INTEGER,
    bet_amount INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    challenger_roll INTEGER,
    opponent_roll INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (challenger_id) REFERENCES users(user_id),
    FOREIGN KEY (opponent_id) REFERENCES users(user_id)
);

-- Player debts
CREATE TABLE IF NOT EXISTS player_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debtor_id INTEGER NOT NULL,
    creditor_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (debtor_id) REFERENCES users(user_id),
    FOREIGN KEY (creditor_id) REFERENCES users(user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_event_history_user_id ON event_history(user_id);
CREATE INDEX IF NOT EXISTS idx_event_history_created_at ON event_history(created_at);
CREATE INDEX IF NOT EXISTS idx_user_groups_chat_id ON user_groups(chat_id);
CREATE INDEX IF NOT EXISTS idx_dice_challenges_status ON dice_challenges(status);

-- ============================================================
-- DOWNGRADE
-- ============================================================

-- To rollback:
-- DROP TABLE IF EXISTS player_debts;
-- DROP TABLE IF EXISTS dice_challenges;
-- DROP TABLE IF EXISTS user_groups;
-- DROP TABLE IF EXISTS ai_dialogue_messages;
-- DROP TABLE IF EXISTS ai_credit_sessions;
-- DROP TABLE IF EXISTS event_history;
-- DROP TABLE IF EXISTS users;
```

---

## ✅ Implementation Checklist

### Phase 1: Decision & Setup
- [ ] Обсудить выбор подхода (Alembic vs SQL Scripts)
- [ ] Зафиксировать решение в `logs/dev_diary.md`
- [ ] Создать структуру `migrations/`

### Phase 2: Migration Runner
- [ ] Создать `migration_runner.py`
- [ ] Создать таблицу `schema_versions`
- [ ] Протестировать на пустой БД

### Phase 3: Baseline Migration
- [ ] Создать `001_initial_schema.sql` из текущей схемы
- [ ] Применить на тестовой БД
- [ ] Проверить, что все таблицы созданы корректно

### Phase 4: Documentation
- [ ] Создать `migrations/README.md` с инструкциями
- [ ] Обновить `AGENTS.md` (секция "Database Migrations")
- [ ] Создать `template.sql` для новых миграций

### Phase 5: Workflow Integration
- [ ] Добавить проверку версии при старте бота (optional)
- [ ] Документировать процесс создания новой миграции
- [ ] Добавить в CI/CD (TASK-012)

---

## 🧪 Testing & Validation

### Manual Testing
```bash
# 1. Backup существующей БД
cp telegram-casino-bot/bot/casino.db telegram-casino-bot/bot/casino.db.backup

# 2. Создать тестовую пустую БД
rm telegram-casino-bot/bot/casino_test.db
# Update DB_PATH in migration_runner.py

# 3. Применить миграции
python migrations/migration_runner.py

# 4. Проверить схему
sqlite3 telegram-casino-bot/bot/casino_test.db ".schema"

# 5. Запустить бота с новой БД — должен работать
```

### Success Metrics
- Миграции применяются без ошибок
- Все таблицы и индексы созданы корректно
- Бот корректно работает с новой БД
- Можно откатить миграцию (если реализован downgrade)

---

## 📦 Dependencies

**Before this task:**
- Существующая схема БД (в `bot/db.py`)

**After this task:**
- Используется при добавлении новых фич (new columns, tables)
- Используется в CI/CD для автоматического применения миграций

---

## 📝 Notes

### Why SQL Scripts Over Alembic?
1. **Simplicity**: Не нужна ещё одна зависимость
2. **Control**: Полный контроль над SQL для game-critical логики
3. **No ORM**: Alembic лучше работает с SQLAlchemy, которого у нас нет
4. **Transparency**: SQL легче ревьюить в PR

### Migration Workflow
```
1. Новая фича требует изменения схемы
2. Создать файл `00X_description.sql`
3. Написать UPGRADE секцию
4. Написать DOWNGRADE секцию (optional)
5. Применить: `python migrations/migration_runner.py`
6. Протестировать фичу
7. Закоммитить миграцию вместе с кодом
```

### Naming Convention
```
001_initial_schema.sql
002_add_heist_tables.sql
003_add_safe_balance.sql
004_add_user_nickname_index.sql
```
- 3-digit version number
- Underscore separator
- Lowercase, descriptive name

### Production Considerations
```bash
# Before deploy:
1. Backup БД: `cp casino.db casino.db.backup`
2. Применить миграции: `python migrations/migration_runner.py`
3. Если ошибка — откатить из backup
4. Если успех — deploy новой версии бота
```

### Auto-apply on Bot Start (Optional)
```python
# bot/__main__.py
from migrations.migration_runner import run_migrations

async def main():
    # Apply pending migrations
    await run_migrations()
    
    # Start bot
    await dp.start_polling(bot)
```

---

## 🔗 References

- Alembic docs: https://alembic.sqlalchemy.org/
- SQLite ALTER TABLE: https://www.sqlite.org/lang_altertable.html
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 7)
- `@bot/db.py` (текущая схема)
