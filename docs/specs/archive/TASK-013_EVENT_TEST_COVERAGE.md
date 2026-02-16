# TASK-013: Comprehensive Event Test Coverage

**ID**: TASK-013  
**Title**: Тестовое покрытие рекомендуемых игровых событий  
**Priority**: HIGH  
**Status**: SPEC_READY  
**Created**: 2026-02-16  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-013-1: Event coverage matrix
Создать единый список рекомендуемых событий и обязательных сценариев проверки.

**Acceptance Criteria:**
- В спецификации есть матрица `event -> source -> expected behavior -> expected DB event`.
- Покрыты команды: `/give`, `/safe`, `/dice`, `/take`, `/stats`, `/top`.
- Покрыты scheduler-сценарии: timeout принятия дуэли, timeout броска.
- Покрыты ключевые event types из `event_history` для core game loops.

### REQ-013-2: Integration tests for command handlers
Добавить интеграционные тесты обработчиков с фейковыми Telegram-событиями.

**Acceptance Criteria:**
- Для каждой целевой команды есть минимум 1 позитивный и 1 негативный сценарий.
- Проверяются и ответы бота, и эффекты в БД (balance/debt/event_history).
- Тесты изолированы (временная SQLite БД, без side effects).

### REQ-013-3: Timeout and scheduler behavior
Добавить тесты истечения вызовов и авто-бросков.

**Acceptance Criteria:**
- Проверяется истечение pending challenge по `challenge_timeout_minutes`.
- Проверяется авто-бросок при истечении `roll_timeout_minutes`.
- Проверяется, что после timeout дуэль завершается в валидный исход (`win/loss/draw`) без exception.

### REQ-013-4: Regression guard for /stats and /top
Добавить тесты на разделение ответственности `/stats` и `/top`.

**Acceptance Criteria:**
- `/stats` проверяется как индивидуальная статистика игрока.
- `/top` проверяется как топ-10 игроков группы.
- Отдельно проверяются медали для топ-3.
- Если вызывающий вне топ-10, проверяется строка с его позицией внизу ответа.

### REQ-013-5: Test execution profile
Убедиться, что все новые тесты запускаются текущим пайплайном.

**Acceptance Criteria:**
- `./scripts/test.sh` проходит с новыми тестами.
- Маркировка тестов соответствует текущей структуре `tests/unit` и `tests/integration`.
- Тесты не требуют внешних API (AI provider/real Telegram).

---

## 🎯 Goals

**Primary Goal:**  
Защитить проект от регрессий после рефакторингов, особенно в командах, таймаутах дуэлей и записи событий.

**Why This Matters:**
- **Stability**: баги сигнатур DI и scheduler ловятся до деплоя.
- **Confidence**: изменения в хендлерах и репозиториях не ломают соседние флоу.
- **Faster incident response**: проще локализовать причину по проваленному сценарию.
- **Safer releases**: меньше “в коде есть, в рантайме не работает”.

---

## 📐 Design

### Coverage scope (recommended events)

#### A) Command-level flows
- `/give`: успешный перевод, отказ при нехватке средств, валидация target.
- `/safe`: просмотр, депозит, вывод, блокировка депозита при активной дуэли.
- `/dice`: создание вызова, лимит ставки с учетом долгов.
- `/take`: успешное взыскание, отказ при отсутствии долга/перевышении суммы.
- `/stats`: своя статистика и `@username`.
- `/top`: топ-10, медали 1-3, строка позиции вызывающего вне топа.

#### B) Duel timeout flows
- pending challenge -> cancelled by timeout.
- accepted/rolling challenge with missing roll -> auto-roll -> resolved duel.

#### C) Core `event_history` invariants (минимальный набор)
- `win`, `loss`, `bankruptcy`
- `transfer_in`, `transfer_out`
- `dice_challenge_win`, `dice_challenge_loss`, `dice_challenge_draw`
- `debt_created`, `debt_paid` (где применимо в текущей реализации)

### Test architecture
- **Integration first**: тесты через хендлеры и репозитории на временной SQLite.
- **Minimal mocking**: мокать Telegram `Message`/`CallbackQuery` и Bot API calls.
- **Deterministic outcomes**: для случайностей (roll phrases) использовать controlled seeds/patches.

---

## ✅ Implementation Checklist

### Phase 1: Test contracts
- [ ] Составить таблицу сценариев по REQ-013-1.
- [ ] Для каждого сценария зафиксировать ожидаемый bot reply и DB side effects.

### Phase 2: Handlers integration tests
- [ ] Добавить тесты для `/give` и `/safe`.
- [ ] Добавить тесты для `/dice` и `/take`.
- [ ] Добавить тесты для `/stats` и `/top` (включая top-10 и medals).

### Phase 3: Scheduler/timeout tests
- [ ] Добавить тесты `get_expired_challenges_with_message`.
- [ ] Добавить тесты `get_timed_out_duels`.
- [ ] Добавить тест на `auto_roll_for_timeout(...)` и финализацию дуэли.

### Phase 4: Regression assertions
- [ ] Проверить event types в `event_history` по ключевым флоу.
- [ ] Проверить, что обработчики не падают на DI-зависимостях.

### Phase 5: Validation
- [ ] Запустить `./scripts/test.sh`.
- [ ] Запустить `./scripts/lint.sh`.
- [ ] Подготовить короткий отчет покрытия по ключевым событиям.

---

## 🧪 Testing & Validation

### Minimal pass criteria
- Все новые тесты зеленые локально.
- Нет flaky-сценариев на случайных фразах/таймерах.
- Для timeout сценариев есть минимум по одному положительному подтверждению.

### Suggested test modules
- `tests/integration/test_transfer_safe_handlers.py`
- `tests/integration/test_dice_take_handlers.py`
- `tests/integration/test_stats_top_handlers.py`
- `tests/integration/test_duel_timeouts.py`

---

## 📦 Dependencies

**Required before this task:**
- TASK-006 (test structure) — DONE.
- TASK-010 (repository pattern) — DONE.

**Optional, not blocking:**
- TASK-008 (env configs) — желательно для удобного `ENV=test`, но не обязателен для реализации тестов.

---

## 📝 Notes

- В рамках этой задачи акцент на бизнес-сценарии и регрессии, а не на 100% coverage по строкам.
- Если текущая реализация event type отличается от старых спеков, тесты фиксируют фактический контракт кода.
- Для таймаутов предпочтительны тесты уровня repository/service, чтобы избежать дорогих e2e-таймеров.

---

## 🔗 References

- `docs/specs/STATS_TOP_SPEC.md`
- `docs/specs/archive/TASK-006_TEST_STRUCTURE.md`
- `docs/specs/archive/TASK-010_REPOSITORY_PATTERN.md`
- `AGENTS.md` (Development Workflow, skill:validate)
