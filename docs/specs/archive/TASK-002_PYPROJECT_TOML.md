# TASK-002: Modern Python Project Configuration

**ID**: TASK-002  
**Title**: Миграция на pyproject.toml (PEP 518)  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-002-1: pyproject.toml creation
Создать `pyproject.toml` с метаданными проекта и зависимостями.

**Acceptance Criteria:**
- Файл находится в корне проекта `python-runner/pyproject.toml`
- Содержит секцию `[project]` с метаданными
- Содержит секцию `[project.dependencies]` со всеми зависимостями из `requirements.txt`
- Версии зависимостей зафиксированы (например, `aiogram>=3.18.0,<4.0.0`)

### REQ-002-2: Tool configurations
Добавить конфигурации для ruff, pyright, pytest в `pyproject.toml`.

**Acceptance Criteria:**
- `[tool.ruff]` с настройками линтера
- `[tool.pyright]` с настройками type checker
- `[tool.pytest.ini_options]` с настройками тестов
- Все настройки согласованы между инструментами

### REQ-002-3: requirements.txt compatibility
Сохранить `requirements.txt` для обратной совместимости (но генерировать его из pyproject.toml).

**Acceptance Criteria:**
- `requirements.txt` остаётся в проекте
- Добавлен комментарий "Generated from pyproject.toml"
- Можно установить зависимости через `pip install -r requirements.txt` (для CI/Docker)

### REQ-002-4: Documentation update
Обновить документацию для отражения новой структуры.

**Acceptance Criteria:**
- `AGENTS.md` обновлён (секция "Запуск")
- Добавлена инструкция `pip install -e .` для dev окружения
- README содержит ссылку на pyproject.toml

---

## 🎯 Goals

**Primary Goal:**
Перейти на современный стандарт управления Python-проектами (PEP 518/621) для улучшения developer experience и интеграции с инструментами.

**Why This Matters:**
- Единая точка конфигурации всех инструментов
- LSP (Pyright) автоматически подхватывает типы и зависимости
- Упрощается установка проекта: `pip install -e .` vs `pip install -r requirements.txt`
- Поддержка editable installs для разработки

---

## 📐 Design

### pyproject.toml structure
```toml
[project]
name = "left4casino-bot"
version = "1.0.0"
description = "Telegram casino bot with AI banker"
requires-python = ">=3.11"
dependencies = [
    "aiogram>=3.18.0,<4.0.0",
    "aiosqlite>=0.19.0",
    "openai>=1.0.0",
    "apscheduler>=3.10.4",
    "structlog>=25.1.0",
    "redis>=5.2.1",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.3.0",
    "pyright>=1.1.350",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]

[tool.pyright]
typeCheckingMode = "basic"
reportMissingTypeStubs = false
pythonVersion = "3.11"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Migration Strategy
1. Создать `pyproject.toml` с содержимым из `requirements.txt`
2. Добавить конфигурации инструментов
3. Обновить `requirements.txt` (оставить для совместимости)
4. Обновить документацию

---

## ✅ Implementation Checklist

- [x] Прочитать текущий `requirements.txt`
- [x] Создать `pyproject.toml` с секцией `[project]`
- [x] Добавить все зависимости с версиями
- [x] Добавить `[tool.ruff]` конфигурацию
- [x] Добавить `[tool.pyright]` конфигурацию
- [x] Добавить `[tool.pytest.ini_options]` конфигурацию
- [x] Добавить комментарий в `requirements.txt`
- [x] Обновить `AGENTS.md` (секция "Запуск")
- [x] Тестовая установка: `pip install -e .`

---

## 🧪 Testing & Validation

### Manual Testing
1. `pip install -e .` в виртуальном окружении — должно установиться без ошибок
2. `python main.py` — бот должен запуститься как обычно
3. `ruff check .` — должно использовать настройки из pyproject.toml
4. `pyright` — должно использовать настройки из pyproject.toml

### Success Metrics
- Все зависимости устанавливаются корректно
- LSP в Cursor подхватывает типы из библиотек
- Нет breaking changes для существующего workflow

---

## 📦 Dependencies

**Before this task:**
- `requirements.txt` существует и актуален
- Проект запускается и работает

**Blocks:**
- TASK-003 (ruff/pyright setup) — зависит от pyproject.toml

**After this task:**
- Используется как source of truth для зависимостей
- Все инструменты читают конфиг из pyproject.toml

---

## 📝 Notes

### Versioning Strategy
- Мажорные версии: `>=X.Y.0,<X+1.0.0` (например, `aiogram>=3.18.0,<4.0.0`)
- Минорные версии: `>=X.Y.Z` (более свободно для патчей)

### Optional Dependencies
- `[project.optional-dependencies]` для dev-инструментов (pytest, ruff)
- Устанавливается через `pip install -e ".[dev]"`

### Backwards Compatibility
- **НЕ удаляем** `requirements.txt` сразу — Docker и CI могут использовать его
- Можно генерировать его автоматически: `pip freeze > requirements.txt`

---

## 🔗 References

- PEP 518: https://peps.python.org/pep-0518/
- PEP 621: https://peps.python.org/pep-0621/
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 2)
- `@requirements.txt` (текущие зависимости)
