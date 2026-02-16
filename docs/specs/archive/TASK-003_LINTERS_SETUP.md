# TASK-003: Linters and Type Checking Setup

**ID**: TASK-003  
**Title**: Настройка ruff и pyright для качества кода  
**Priority**: HIGH  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-003-1: Ruff configuration
Настроить ruff как primary линтер и форматтер.

**Acceptance Criteria:**
- `[tool.ruff]` в `pyproject.toml` содержит базовые правила
- Line length = 100 (согласовано с командой)
- Включены rules: E (pycodestyle errors), F (pyflakes), I (isort), N (pep8-naming), W (warnings)
- Игнорируется E501 (line too long) для длинных строк
- `ruff check .` проходит без критичных ошибок на существующем коде

### REQ-003-2: Pyright configuration
Настроить pyright для статической проверки типов.

**Acceptance Criteria:**
- `[tool.pyright]` в `pyproject.toml` с режимом "basic" (не strict на первом этапе)
- `pythonVersion = "3.11"` соответствует используемой версии
- `reportMissingTypeStubs = false` (чтобы не спамить на библиотеки без типов)
- `pyright` выполняется без критичных ошибок на существующем коде

### REQ-003-3: Pre-commit integration (optional)
Добавить `.pre-commit-config.yaml` для автоматической проверки перед коммитом.

**Acceptance Criteria:**
- Файл `.pre-commit-config.yaml` создан
- Включены hooks: ruff (lint + format), pyright
- `pre-commit install` устанавливает hooks
- При коммите автоматически запускаются проверки

### REQ-003-4: CI integration placeholder
Подготовить структуру для будущей CI интеграции.

**Acceptance Criteria:**
- Создан `scripts/lint.sh` с командами `ruff check` и `pyright`
- Скрипт возвращает exit code 1 при ошибках
- Добавлен в документацию как рекомендуемая проверка перед push

---

## 🎯 Goals

**Primary Goal:**
Внедрить автоматическую проверку качества кода (линтинг, форматирование, типизация) для снижения количества багов и улучшения консистентности кодовой базы.

**Why This Matters:**
- **Предотвращение багов**: 30-40% ошибок отлавливаются до запуска кода
- **Консистентность**: Весь код выглядит одинаково (упрощает code review)
- **AI-friendly**: Pyright предоставляет типы, которые Cursor использует для автодополнения
- **Галлюцинации AI**: Статическая типизация не даёт AI передать `str` вместо `int`

---

## 📐 Design

### Ruff Configuration
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

# Enable specific rule sets
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "I",   # isort (import sorting)
    "N",   # pep8-naming
    "W",   # pycodestyle warnings
    "UP",  # pyupgrade (modern Python syntax)
    "B",   # flake8-bugbear (common bugs)
]

# Ignore specific rules
ignore = [
    "E501",  # line too long (handled by formatter)
]

# Exclude directories
extend-exclude = [
    "__pycache__",
    "*.egg-info",
    ".venv",
    "telegram-casino-bot/bot/locale",  # Generated files
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### Pyright Configuration
```toml
[tool.pyright]
typeCheckingMode = "basic"  # Start with basic, upgrade to strict later
pythonVersion = "3.11"
pythonPlatform = "Linux"

# Include/exclude
include = ["telegram-casino-bot/bot", "main.py"]
exclude = [
    "**/__pycache__",
    "**/node_modules",
]

# Reporting
reportMissingTypeStubs = false
reportUnknownMemberType = false
reportUnknownVariableType = false
reportUnknownArgumentType = false

# Strictness (can be enabled later)
# reportOptionalMemberAccess = "error"
# reportOptionalCall = "error"
```

### Pre-commit Config
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  
  - repo: https://github.com/RobertCraigie/pyright-python
    rev: v1.1.350
    hooks:
      - id: pyright
```

### Lint Script
```bash
#!/bin/bash
# scripts/lint.sh
set -e

echo "Running ruff check..."
ruff check .

echo "Running ruff format check..."
ruff format --check .

echo "Running pyright..."
pyright

echo "✓ All checks passed!"
```

---

## ✅ Implementation Checklist

### Phase 1: Configuration
- [ ] Обновить `pyproject.toml` с `[tool.ruff]`
- [ ] Обновить `pyproject.toml` с `[tool.pyright]`
- [ ] Установить зависимости: `pip install ruff pyright`

### Phase 2: Initial Cleanup
- [ ] Запустить `ruff check . --fix` для автоматических фиксов
- [ ] Запустить `ruff format .` для форматирования кода
- [ ] Запустить `pyright` и проверить количество ошибок
- [ ] Если ошибок > 50 — ослабить strictness (уже в "basic" режиме)

### Phase 3: Pre-commit (optional)
- [ ] Создать `.pre-commit-config.yaml`
- [ ] Добавить в `[project.optional-dependencies]`: `pre-commit>=3.6.0`
- [ ] Документировать установку: `pre-commit install`

### Phase 4: Scripts & Docs
- [ ] Создать `scripts/lint.sh`
- [ ] Добавить в `AGENTS.md` секцию "Quality Checks"
- [ ] Обновить `.cursorrules` для упоминания линтеров

---

## 🧪 Testing & Validation

### Baseline Check (Before Cleanup)
```bash
# Подсчитать текущие ошибки
ruff check . --statistics
pyright --stats
```

### After Cleanup
```bash
# Должно быть 0 errors, допустимы warnings
ruff check .
ruff format --check .
pyright
```

### Manual Testing
1. Создать тестовый файл с ошибками:
```python
# test_lint.py
import os, sys  # I001: import not sorted

def myFunc(x):  # N802: function name should be lowercase
    if x==5:  # E225: missing whitespace
        return "hello"
```

2. Запустить `ruff check test_lint.py` — должны быть найдены ошибки
3. Запустить `ruff check test_lint.py --fix` — должны быть автоматически исправлены
4. Удалить `test_lint.py`

### Success Metrics
- Рабочий код проходит все проверки
- Автофикс работает для большинства правил
- Cursor использует типы из pyright для автодополнения

---

## 📦 Dependencies

**Before this task:**
- TASK-002 (pyproject.toml) — **REQUIRED** (конфиги добавляются туда)

**After this task:**
- Используется в pre-commit hooks
- Используется в будущем CI/CD (TASK-012)
- LSP Cursor подхватывает типы

---

## 📝 Notes

### Ruff vs Black/Flake8/isort
- Ruff заменяет сразу 10+ инструментов
- **В 10-100 раз быстрее** старых линтеров (написан на Rust)
- Автофикс для большинства правил

### Pyright vs MyPy
- Pyright используется VSCode/Cursor по умолчанию
- Быстрее MyPy (Node.js vs Python)
- Лучше интеграция с LSP

### Strictness Strategy
- Начинаем с `basic` режима (мало ошибок)
- Постепенно включаем strictness по мере добавления типов:
  ```toml
  typeCheckingMode = "standard"  # После добавления типов
  # typeCheckingMode = "strict"  # Конечная цель
  ```

### Known Issues
- Могут быть ложные срабатывания на `aiogram` (нет полных type stubs)
- Решение: добавить `# type: ignore` локально или в pyright ignore

---

## 🔗 References

- Ruff docs: https://docs.astral.sh/ruff/
- Pyright docs: https://microsoft.github.io/pyright/
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 4)
- `@TASK-002_PYPROJECT_TOML.md` (требуется для конфига)
