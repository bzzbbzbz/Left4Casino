# TASK-008: Environment-Based Configuration

**ID**: TASK-008  
**Title**: Разделение конфигов по окружениям (dev/test/prod)  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-008-1: Config directory structure
Создать структуру для конфигурационных файлов.

**Acceptance Criteria:**
- Создана директория `config/` в корне проекта
- Создан `config/settings.base.toml` с базовыми настройками
- Создан `config/settings.dev.toml` для локальной разработки
- Создан `config/settings.test.toml` для тестирования
- Создан `config/settings.prod.toml` для продакшна
- Создан `config/settings.example.toml` как шаблон

### REQ-008-2: Config loading logic
Реализовать логику выбора конфига по переменной окружения.

**Acceptance Criteria:**
- Переменная `ENV` определяет окружение (dev/test/prod)
- Загружается base + environment-specific конфиг
- Environment-specific настройки переопределяют базовые
- Fallback на dev если ENV не указана
- Код загрузки в `bot/config_reader.py`

### REQ-008-3: Environment-specific differences
Настроить различия между окружениями.

**Acceptance Criteria (dev):**
- БД: `casino_dev.db` (не трогает prod БД)
- Redis: `localhost:6379` (или memory mode)
- AI: Mock provider или дешёвая модель
- Логи: DEBUG level в консоль
- Timeouts: Укороченные для быстрого тестирования

**Acceptance Criteria (test):**
- БД: `:memory:` (in-memory SQLite)
- Redis: Memory FSM mode
- AI: Mock provider (без реальных API-вызовов)
- Логи: WARNING level
- Timeouts: Минимальные

**Acceptance Criteria (prod):**
- БД: `casino.db` (production)
- Redis: Remote Redis DSN из env
- AI: OpenRouter с production ключом
- Логи: INFO level в файл
- Timeouts: Реальные значения из спек

### REQ-008-4: Documentation and safety
Документировать конфиги и предотвратить случайные ошибки.

**Acceptance Criteria:**
- `.gitignore` содержит `config/settings.prod.toml` (не коммитить секреты)
- Создан `config/README.md` с инструкциями
- В `AGENTS.md` описан процесс выбора окружения
- Предупреждение в логах при старте: "Running in DEV mode"

---

## 🎯 Goals

**Primary Goal:**
Изолировать окружения для безопасной разработки без риска повлиять на продакшн-данные.

**Why This Matters:**
- **Safety**: Невозможно случайно запустить тесты на боевой БД
- **Flexibility**: Разработчики могут иметь укороченные timeouts для быстрой проверки
- **Team Collaboration**: Каждый может иметь свои dev-настройки без конфликтов
- **Production Security**: Секреты production не хранятся в Git

---

## 📐 Design

### Directory Structure
```
config/
├── README.md                    # Инструкции
├── settings.base.toml           # Базовые настройки (общие для всех)
├── settings.dev.toml            # Локальная разработка
├── settings.test.toml           # Тестирование (in-memory, моки)
├── settings.prod.toml           # Продакшн (не в Git!)
└── settings.example.toml        # Шаблон для копирования
```

### settings.base.toml (Shared Config)
```toml
# config/settings.base.toml
# Base configuration shared across all environments

[bot]
fsm_mode = "redis"

[game_config]
starting_points = 50
throttle_time_spin = 2
throttle_time_other = 1
throttle_time_top = 5

[chat_restrictions]
block_private_chats = false
# allowed_chat_ids are environment-specific

[ai]
provider = "openrouter"
model = "deepseek/deepseek-chat"
credit_cooldown_minutes = 15

[reports]
timezone = "Asia/Yekaterinburg"

[dice_fights]
challenge_timeout_minutes = 5
roll_timeout_minutes = 5
max_debt = 100
min_bet = 1

[happy_moment]
enabled = true
events_per_day = 2
active_hours_weight = 90
active_hours_start = "08:00"
active_hours_end = "02:00"

[[happy_moment.tiers]]
duration_minutes = 1
multiplier = 5.0

[[happy_moment.tiers]]
duration_minutes = 2
multiplier = 4.0

[[happy_moment.tiers]]
duration_minutes = 3
multiplier = 3.0

[heist]
enabled = true
pot_cap_multiplier = 0.05
min_pot_multiplier = 0.01
commission_pct = 10
phase1_min_duration = 10
phase1_max_duration = 25
phase2_min_duration = 2
phase2_max_duration = 5
```

### settings.dev.toml (Development)
```toml
# config/settings.dev.toml
# Development environment - local testing with fast iteration

[bot]
token = "${BOT_TOKEN_DEV}"  # From environment variable
fsm_mode = "memory"  # No Redis needed for dev

[database]
path = "telegram-casino-bot/bot/casino_dev.db"  # Separate dev DB

[redis]
dsn = "redis://localhost:6379"  # Local Redis (if fsm_mode=redis)

[chat_restrictions]
allowed_chat_ids = [-1001234567890, -1009876543210]  # Dev test groups

[ai]
provider = "mock"  # Use mock AI for fast testing
# or use cheap model:
# model = "deepseek/deepseek-chat"

[reports]
admin_id = 123456789  # Your dev Telegram ID

[logging]
level = "DEBUG"
output = "console"

# Shortened timeouts for fast testing
[dice_fights]
challenge_timeout_minutes = 1  # 1 min instead of 5
roll_timeout_minutes = 1

[heist]
phase1_min_duration = 2  # 2 min instead of 10
phase1_max_duration = 5  # 5 min instead of 25
phase2_min_duration = 1
phase2_max_duration = 2

[happy_moment]
events_per_day = 10  # More frequent for testing
```

### settings.test.toml (Testing)
```toml
# config/settings.test.toml
# Testing environment - for pytest, no real APIs

[bot]
token = "123456:TEST_TOKEN"
fsm_mode = "memory"

[database]
path = ":memory:"  # In-memory SQLite

[redis]
dsn = ""  # Not used in memory mode

[chat_restrictions]
allowed_chat_ids = [-100123]  # Test chat ID

[ai]
provider = "mock"  # Always mock in tests

[reports]
admin_id = 999999999  # Test admin ID

[logging]
level = "WARNING"  # Less noise in tests
output = "console"

# Minimal timeouts for fast tests
[dice_fights]
challenge_timeout_minutes = 0  # Instant timeout
roll_timeout_minutes = 0

[heist]
enabled = false  # Disable scheduled tasks in tests

[happy_moment]
enabled = false  # Disable scheduled tasks in tests
```

### settings.prod.toml (Production)
```toml
# config/settings.prod.toml
# Production environment - NEVER commit this file!
# Use .gitignore to exclude it

[bot]
token = "${BOT_TOKEN}"  # From environment variable (required!)

[database]
path = "telegram-casino-bot/bot/casino.db"  # Production DB

[redis]
dsn = "${REDIS_DSN}"  # From environment variable

[chat_restrictions]
allowed_chat_ids = [-1001111111111, -1002222222222]  # Real groups

[ai]
provider = "openrouter"
model = "deepseek/deepseek-chat"
# OPENROUTER_API_KEY from environment

[reports]
admin_id = 111222333  # Real admin ID

[logging]
level = "INFO"
output = "file"
file_path = "logs/bot.log"

# Production timeouts (from specs)
[dice_fights]
challenge_timeout_minutes = 5
roll_timeout_minutes = 5

[heist]
phase1_min_duration = 10
phase1_max_duration = 25
phase2_min_duration = 2
phase2_max_duration = 5
```

### Config Loader (bot/config_reader.py)
```python
"""Environment-aware configuration loader"""
import os
import tomli
from pathlib import Path
from typing import Dict, Any

def merge_configs(base: Dict[Any, Any], override: Dict[Any, Any]) -> Dict[Any, Any]:
    """Recursively merge override config into base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result

def expand_env_vars(config: Dict[Any, Any]) -> Dict[Any, Any]:
    """Expand ${VAR} references to environment variables"""
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = expand_env_vars(value)
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            result[key] = os.getenv(env_var, value)
        else:
            result[key] = value
    return result

def load_config(env: str = None) -> Dict[Any, Any]:
    """Load configuration for specified environment"""
    if env is None:
        env = os.getenv("ENV", "dev")
    
    config_dir = Path(__file__).parent.parent.parent / "config"
    
    # Load base config
    base_path = config_dir / "settings.base.toml"
    with open(base_path, "rb") as f:
        config = tomli.load(f)
    
    # Load environment-specific config
    env_path = config_dir / f"settings.{env}.toml"
    if env_path.exists():
        with open(env_path, "rb") as f:
            env_config = tomli.load(f)
        config = merge_configs(config, env_config)
    else:
        print(f"⚠️  Warning: No config found for environment '{env}', using base only")
    
    # Expand environment variables
    config = expand_env_vars(config)
    
    # Log environment
    print(f"🚀 Running in {env.upper()} mode")
    if env == "dev":
        print("⚠️  DEV mode: Using dev database and mocked services")
    
    return config

# Usage
config = load_config()
```

---

## ✅ Implementation Checklist

### Phase 1: Structure
- [ ] Создать `config/` директорию
- [ ] Создать `settings.base.toml` с общими настройками
- [ ] Создать `settings.dev.toml` с dev настройками
- [ ] Создать `settings.test.toml` с test настройками
- [ ] Создать `settings.prod.toml` (скопировать в `.gitignore`!)

### Phase 2: Config Loader
- [ ] Обновить `bot/config_reader.py` с логикой выбора env
- [ ] Реализовать `merge_configs()` для объединения конфигов
- [ ] Реализовать `expand_env_vars()` для подстановки `${VAR}`
- [ ] Добавить логирование выбранного окружения

### Phase 3: Integration
- [ ] Обновить `bot/__main__.py` для использования нового загрузчика
- [ ] Протестировать запуск в dev режиме
- [ ] Протестировать запуск в test режиме (for pytest)
- [ ] Создать `config/settings.prod.toml` для продакшна

### Phase 4: Safety & Docs
- [ ] Добавить `config/settings.prod.toml` в `.gitignore`
- [ ] Создать `config/README.md` с инструкциями
- [ ] Создать `config/settings.example.toml` как шаблон
- [ ] Обновить `AGENTS.md` (секция "Configuration")

---

## 🧪 Testing & Validation

### Manual Testing
```bash
# Test dev environment
ENV=dev python main.py
# Should use casino_dev.db, print "Running in DEV mode"

# Test test environment
ENV=test pytest tests/
# Should use :memory: DB, mock AI

# Test prod environment (dry-run)
ENV=prod python -c "from bot.config_reader import load_config; print(load_config())"
# Should load prod config, expand env vars
```

### Success Metrics
- Запуск в dev не трогает prod БД
- Запуск тестов использует in-memory БД
- Prod конфиг не коммитится в Git
- Переключение между окружениями работает через `ENV`

---

## 📦 Dependencies

**Before this task:**
- Существующий `settings.toml` (будет мигрирован в `config/`)

**After this task:**
- Используется всеми компонентами бота
- Упрощает тестирование (TASK-006)
- Безопасное развертывание в продакшн

---

## 📝 Notes

### .gitignore Updates
```gitignore
# Production config (contains secrets)
config/settings.prod.toml

# Local overrides
config/settings.local.toml

# Dev database
telegram-casino-bot/bot/casino_dev.db
```

### Environment Variable Priority
```
1. Environment variables (${BOT_TOKEN})
2. Environment-specific config (settings.dev.toml)
3. Base config (settings.base.toml)
```

### Docker Integration
```dockerfile
# Dockerfile
ENV ENV=prod
COPY config/settings.base.toml /app/config/
# settings.prod.toml provided at runtime via volume or secret
```

### CI/CD Integration
```yaml
# .github/workflows/test.yml
env:
  ENV: test
steps:
  - name: Run tests
    run: pytest tests/
```

---

## 🔗 References

- TOML spec: https://toml.io/
- 12-Factor App: https://12factor.net/config
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 8)
- `@bot/config_reader.py` (текущая реализация)
