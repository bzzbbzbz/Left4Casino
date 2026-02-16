# TASK-014: Schedule Visibility and Idempotency

**ID**: TASK-014  
**Title**: Персистентность расписания Happy Moment/Heist и диагностика ближайших ивентов  
**Priority**: HIGH  
**Status**: SPEC_READY  
**Created**: 2026-02-16  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-014-1: Persist generated schedule in storage
После генерации расписания на день для `happy_moment` и `heist` данные должны сохраняться в БД, а не только в памяти процесса.

**Acceptance Criteria:**
- Добавлена персистентная сущность расписания (таблица/модель) для будущих ивентов.
- Для каждого события сохраняются минимум: `event_type`, `chat_id` (или global), `scheduled_at`, `timezone`, `payload/metadata`, `status`.
- При повторной генерации на тот же день выполняется идемпотентное обновление (upsert), без дублей.
- Сохранённые записи доступны для чтения отдельным утилитарным скриптом.

### REQ-014-2: Startup rehydration and no duplicate daily events
При рестарте бот должен восстанавливать будущие задачи из сохранённого расписания и не создавать лишние события на текущие сутки.

**Acceptance Criteria:**
- На старте бот сначала пытается загрузить расписание текущего дня из БД.
- Если валидное расписание уже существует, бот планирует jobs на его основе и НЕ генерирует новое.
- Если расписания нет (или оно просрочено/битое), генерируется новое и сохраняется.
- Количество ивентов в сутки соответствует конфигу (например, `events_per_day` для happy moment и 1 heist/day), даже после нескольких рестартов.

### REQ-014-3: Runtime schedule introspection script
Создать скрипт на основе `get_heist_info.py`, который показывает ближайшие запланированные ивенты.

**Acceptance Criteria:**
- Добавлен отдельный CLI-скрипт (например, `get_schedule_info.py`) в `python-runner`.
- Скрипт выводит ближайшие future-ивенты по двум типам: `happy_moment` и `heist`.
- Для каждого события отображаются: дата/время, источник (persisted), статус, оставшееся время до запуска.
- Есть режим вывода по умолчанию для текущего дня и расширенный режим (например, `--limit`, `--all`).

### REQ-014-4: Scheduler safety guards
В планировщике должны быть защитные проверки против повторного добавления одноимённых jobs.

**Acceptance Criteria:**
- Job IDs строятся детерминированно и стабильно из persisted schedule entries.
- Перед добавлением jobs выполняется явная идемпотентная логика (replace/update), исключающая дубли.
- После завершения ивента статус записи обновляется (`done` / `expired`), чтобы инспекция отражала фактическое состояние.

---

## 🎯 Goals

**Primary Goal:**  
Сделать расписание будущих событий наблюдаемым и предсказуемым, а поведение планировщика — устойчивым к рестартам.

**Why This Matters:**
- **Observability**: можно быстро проверить, когда будут следующие happy/heist события.
- **Correctness**: исключаются «лишние» события в сутки после перезапусков.
- **Ops confidence**: проще диагностировать работу планировщика в проде.
- **Supportability**: меньше ручной проверки через логи и догадки.

---

## 📐 Design

### Storage contract (proposed)
Добавить таблицу расписания (пример):

```sql
scheduled_events (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,          -- happy_moment_start | heist_warning | heist_start
  chat_id INTEGER,                   -- NULL для глобального события
  scheduled_at TEXT NOT NULL,        -- ISO datetime (UTC)
  timezone TEXT NOT NULL,
  source_date TEXT NOT NULL,         -- "YYYY-MM-DD" в локальной TZ
  status TEXT NOT NULL,              -- scheduled | running | done | expired | cancelled
  metadata TEXT,                     -- JSON payload (tier, multiplier, warning offset, etc.)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

### Integration points
- `bot/services/happy_moment.py`:
  - генерация расписания возвращает структуру для persist слоя;
  - загрузка расписания текущего дня из БД перед генерацией нового.
- `bot/services/heist.py`:
  - аналогично: persistent scheduled start (+ warning);
  - запрет повторной генерации при наличии валидной записи на день.
- `bot/__main__.py`:
  - startup sequence: `load persisted -> schedule jobs -> fallback generate`.
  - cron в 00:00 использует тот же идемпотентный путь, а не «слепую» генерацию.

### Introspection script
- Новый скрипт уровня `python-runner`, построенный по структуре `get_heist_info.py`:
  - подключение к `casino.db`;
  - выборка из persisted schedule таблицы;
  - форматированный вывод ближайших событий.

---

## ✅ Implementation Checklist

### Phase 1: Persistence layer
- [ ] Спроектировать и добавить миграцию для таблицы расписания.
- [ ] Добавить методы DB/repository: create/update/list future events, mark done/expired.
- [ ] Обеспечить upsert по детерминированному ключу события.

### Phase 2: Scheduler idempotency
- [ ] Обновить startup flow в `bot/__main__.py`: rehydrate вместо безусловной генерации.
- [ ] Адаптировать `HappyMomentService` и `HeistService` под persist-first логику.
- [ ] Проверить стабильность job IDs и устранить дубли при рестартах.

### Phase 3: Visibility tooling
- [ ] Создать `get_schedule_info.py` на основе подхода `get_heist_info.py`.
- [ ] Добавить форматированный вывод ближайших ивентов (happy/heist).
- [ ] Добавить опции CLI (минимум `--limit`/`--all` либо эквивалент).

### Phase 4: Runtime statuses
- [ ] При старте/завершении событий обновлять статус persisted записи.
- [ ] Отмечать просроченные неисполненные записи как `expired`.

---

## 🧪 Testing & Validation

### Manual validation scenarios
```bash
# 1) Старт бота: расписание сгенерировано и сохранено
python main.py

# 2) Проверка будущих событий
python get_schedule_info.py

# 3) Перезапуск бота в тот же день
python main.py

# 4) Повторная проверка: количество событий не выросло сверх нормы
python get_schedule_info.py --all
```

### Expected outcomes
- В инспекторе видны ближайшие события и их статусы.
- После 2-3 рестартов в течение дня число событий остаётся константным по конфигу.
- На следующий день создаётся новое расписание, старое корректно архивируется/истекает.

---

## 📦 Dependencies

**Depends on:**
- `TASK-007` (migrations framework) — для добавления таблицы расписания.
- Текущая логика планировщика в `bot/__main__.py`, `bot/services/happy_moment.py`, `bot/services/heist.py`.

**Affected components:**
- DB schema (new table + repository methods)
- Scheduler bootstrap and daily generation path
- Runtime diagnostics script in `python-runner/`

---

## 📝 Notes

- При реализации важно использовать единую таймзону и явную нормализацию времени (рекомендуется хранение в UTC + source_date в локальной TZ).
- Для heist warning/start желательно хранить обе записи как отдельные planned events, чтобы скрипт показывал полную картину.
- Идемпотентность должна проверяться не только `replace_existing=True`, но и на уровне источника расписания (persisted data).

---

## 🔗 References

- `get_heist_info.py`
- `telegram-casino-bot/bot/__main__.py`
- `telegram-casino-bot/bot/services/happy_moment.py`
- `telegram-casino-bot/bot/services/heist.py`
- `docs/specs/HEIST_SPEC.md`
- `docs/specs/HAPPY_MOMENT_SPEC.md`
