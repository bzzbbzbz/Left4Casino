# Feature Specifications

Этот каталог содержит спецификации для разработки Left4Casino бота.

---

## 📁 Структура

### 🚀 Активные задачи (Improvements Pipeline)

Спецификации на улучшение инфраструктуры и качества кода:

| ID | Задача | Приоритет | Статус |
|----|--------|-----------|--------|
| [TASK-001](TASK-001_DEV_DIARY.md) | Development Diary | HIGH | SPEC_READY |
| [TASK-002](TASK-002_PYPROJECT_TOML.md) | pyproject.toml Migration | HIGH | SPEC_READY |
| [TASK-003](TASK-003_LINTERS_SETUP.md) | Ruff + Pyright Setup | HIGH | SPEC_READY |
| [TASK-004](TASK-004_UNIT_TESTS.md) | Basic Unit Tests | HIGH | SPEC_READY |
| [TASK-005](TASK-005_PYDANTIC_MODELS.md) | Pydantic Models | HIGH | SPEC_READY |
| [TASK-006](TASK-006_TEST_STRUCTURE.md) | Test Structure (unit/integration) | MEDIUM | SPEC_READY |
| [TASK-007](TASK-007_DB_MIGRATIONS.md) | Database Migrations | MEDIUM | SPEC_READY |
| [TASK-008](TASK-008_ENV_CONFIGS.md) | Environment Configs (dev/test/prod) | MEDIUM | SPEC_READY |
| [TASK-009](TASK-009_DOCKER_MULTISTAGE.md) | Docker Multi-Stage Build | MEDIUM | SPEC_READY |
| [TASK-010](TASK-010_REPOSITORY_PATTERN.md) | Repository Pattern | MEDIUM | SPEC_READY |
| [TASK-011](TASK-011_SEMANTIC_REGIONS.md) | Semantic Regions Markup | MEDIUM | SPEC_READY |
| [TASK-012](TASK-012_CI_CD.md) | CI/CD (GitHub Actions) | MEDIUM | SPEC_READY |
| [TASK-013](TASK-013_EVENT_TEST_COVERAGE.md) | Comprehensive Event Test Coverage | HIGH | SPEC_READY |

### 🎮 Реализованные фичи (Game Features)

Спецификации игровых механик:

- **AI_AGENT_IMPLEMENTATION_PLAN.md** — ИИ-банкир (кредитная система)
- **DICE_FIGHT_SPEC.md** — PvP дуэли на кубиках с системой долгов
- **SAFE_SPEC.md** — Безопасный счёт (защищённое хранилище очков)
- **STATS_TOP_SPEC.md** — Статистика игроков и рейтинги
- **HAPPY_MOMENT_SPEC.md** — Счастливые миги (временные бонусные периоды)
- **HEIST_SPEC.md** — Ограбление банка (ежедневный ивент)

### 📝 Дополнительные документы

- **HAPPY_MOMENT_QUICK_CHECK.md** — Быстрая проверка механики счастливых мигов
- **CHANGELOG_HEIST_ECONOMY.md** — История изменений экономики ограбления
- **CHANGELOG_NUMBER_FORMATTING.md** — История изменений форматирования чисел

---

## 🔄 Жизненный цикл спецификации

```
┌──────────────┐
│ SPEC_READY   │  ← Спецификация создана и согласована
└──────┬───────┘
       │
┌──────▼────────┐
│ CODE_WRITTEN  │  ← Код реализован согласно спеке
└──────┬────────┘
       │
┌──────▼──────────┐
│ READY_TO_MERGE  │  ← Протестировано, готово к мержу
└──────┬──────────┘
       │
┌──────▼─────┐
│    DONE    │  ← Зафиксировано в logs/dev_diary.md
└────────────┘
```

---

## 📋 Формат спецификации

Каждая спецификация содержит:

### Metadata
- **ID**: Уникальный идентификатор (TASK-XXX)
- **Title**: Краткое название задачи
- **Priority**: HIGH / MEDIUM / LOW
- **Status**: SPEC_READY / CODE_WRITTEN / READY_TO_MERGE / DONE
- **Created**: Дата создания
- **Assignee**: Ответственный (обычно cursor-agent)

### Секции
1. **Requirements** — REQ-XXX-Y с Acceptance Criteria
2. **Goals** — Зачем это нужно (Primary Goal, Why This Matters)
3. **Design** — Архитектурные решения и примеры кода
4. **Implementation Checklist** — Пошаговый план реализации
5. **Testing & Validation** — Как проверить, что работает
6. **Dependencies** — Что должно быть выполнено до/после
7. **Notes** — Дополнительная информация, trade-offs
8. **References** — Ссылки на связанные документы

---

## 🚀 С чего начать?

### Порядок реализации (рекомендуемый)

**Week 1: Foundation**
1. TASK-001 (Dev Diary) — 1 час
2. TASK-002 (pyproject.toml) — 2 часа
3. TASK-003 (Linters) — 3 часа

**Week 2: Testing & Quality**
4. TASK-004 (Unit Tests) — 8 часов
5. TASK-005 (Pydantic Models) — 6 часов

**Week 3: Infrastructure**
6. TASK-006 (Test Structure) — 4 часа
7. TASK-008 (Env Configs) — 3 часа
8. TASK-007 (DB Migrations) — 5 часов

**Week 4: Production Ready**
9. TASK-009 (Docker Multi-Stage) — 4 часа
10. TASK-010 (Repository Pattern) — 8 часов
11. TASK-012 (CI/CD) — 4 часа

**Total estimated time**: ~55 часов

---

## 🎯 Быстрый старт для разработчика

### Создание новой спецификации

1. Скопировать шаблон из существующей TASK-XXX
2. Заполнить metadata (ID, Title, Priority)
3. Описать Requirements с Acceptance Criteria
4. Добавить Design с примерами кода
5. Создать Implementation Checklist
6. Зафиксировать в `status.yaml` (если используется)

### Работа над задачей

```bash
# 1. Прочитать спецификацию
cat docs/specs/TASK-XXX.md

# 2. Обновить статус → CODE_WRITTEN
# (в самом файле или в status.yaml)

# 3. Следовать Implementation Checklist
# [x] Step 1
# [x] Step 2
# [ ] Step 3

# 4. Тестирование по секции Testing & Validation

# 5. Обновить статус → READY_TO_MERGE

# 6. После merge → зафиксировать в logs/dev_diary.md
# 7. Обновить статус → DONE
```

---

## 📚 См. также

- `@AGENTS.md` — Полная документация по архитектуре бота и workflow
- `@.cursorrules` — Правила разработки для AI
- `@docs/PROJECT_IMPROVEMENTS.md` — Подробное обоснование всех улучшений
- `logs/dev_diary.md` — История принятых решений (TODO: создать по TASK-001)

---

## 🤝 Contributing

При добавлении новой спецификации:
1. Используйте формат существующих TASK-XXX файлов
2. Добавьте строку в таблицу "Активные задачи"
3. Укажите Dependencies на другие задачи если есть
4. Создайте чеклист с конкретными шагами

---

**Последнее обновление**: 2026-02-15  
**Версия**: 2.0
