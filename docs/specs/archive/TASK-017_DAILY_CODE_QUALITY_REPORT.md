# TASK-017: Ежедневный отчёт по качеству кода (Docker-логи + OpenCode CLI + отчёт админу)

**ID**: TASK-017  
**Title**: Выгрузка логов Docker за заданный интервал (ошибки/предупреждения), анализ через OpenCode CLI с возможностью довыгрузки логов, отчёт администратору  
**Priority**: MEDIUM  
**Status**: READY_TO_MERGE  
**Created**: 2026-02-23  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-017-1: Время анализа задаётся вручную в настройках
Временное окно для сбора логов задаётся администратором в конфиге (since/until).

**Acceptance Criteria:**
- В секции `[code_quality_report]` задаются параметры временного окна: `log_since` и `log_until` в формате ISO 8601 (например `2026-02-16T15:40:00` или с таймзоной)
- Интерпретация времени — в timezone из `[reports].timezone`, если в строке не указана таймзона
- Допустимы относительные значения (опционально): например `log_since = "24h"` — последние 24 часа от момента запуска джобы; `log_until = "now"` — до текущего времени
- Джоба по расписанию использует это окно при каждом запуске (т.е. при каждом запуске выгружаются логи за заданный интервал)

### REQ-017-2: Выгрузка логов из Docker (ошибки и предупреждения)
Основной источник данных — логи контейнера приложения, отфильтрованные по ключевым словам.

**Acceptance Criteria:**
- Выполняется команда вида: `docker logs <container> --since "<log_since>" --until "<log_until>" 2>&1 | grep -E "(warning|error|Error|Exception)" -i`
- Имя контейнера настраивается в конфиге (например `container_name = "python-runner"`)
- Паттерн фильтра (grep) настраивается в конфиге (по умолчанию `(warning|error|Error|Exception)`)
- Вывод сохраняется в файл с датой в имени, например `code_quality_YYYYMMDD_HHMMSS.txt` в настраиваемой директории (например `/tmp/casino_code_quality/`)
- Опционально в том же артефакте можно сохранять вывод линтеров (ruff, pyright) — см. конфиг `include_lint_output` (по умолчанию false или true — зафиксировать в дизайне)

### REQ-017-3: Агент умеет довыгружать нужные логи для полной картины
OpenCode (или внутренний агент) может запросить дополнительную выгрузку логов без фильтра или за другой интервал.

**Acceptance Criteria:**
- В промпте OpenCode явно указано: при необходимости полного контекста можно запросить довыгрузку логов, выведя строку формата `REQUEST_LOGS: <since_iso> <until_iso>` (один запрос на строку, при необходимости несколько строк)
- Сервис парсит вывод OpenCode на наличие таких строк; для каждой пары since/until выполняет `docker logs <container> --since "<since>" --until "<until>" 2>&1` **без** grep
- Довыгруженный текст добавляется к контексту (в отдельный файл или в общий), после чего выполняется повторный запуск OpenCode с объединённым контекстом (фильтрованные логи + довыгруженные фрагменты) для формирования итогового отчёта с полной картиной
- Ограничение: не более N запросов довыгрузки за один запуск (N настраивается, по умолчанию 3), и ограничение суммарного размера довыгруженного текста (например 100 KB) во избежание переполнения

### REQ-017-4: Анализ через OpenCode CLI
После сохранения вывода логов (и при необходимости довыгрузки) запускать OpenCode CLI для AI-анализа и предложений по исправлениям.

**Acceptance Criteria:**
- Вызов в неинтерактивном режиме: `opencode run "…"` с передачей сохранённого файла (например `--file <path>`)
- Промпт явно просит: проанализировать логи приложения (ошибки/предупреждения), при необходимости запросить довыгрузку по формату REQUEST_LOGS, затем сформировать краткий отчёт для разработчика с предложениями по исправлению/улучшению (язык — русский или из конфига)
- Таймаут на выполнение opencode настраивается (по умолчанию 300 секунд)
- Если `opencode` не в PATH или команда завершилась с ошибкой/таймаутом — не падать; в отчёт админу включить только сырой вывод логов без AI-части

### REQ-017-5: Формирование итогового отчёта
Итоговый отчёт для отправки админу — единое или разбитое сообщение.

**Acceptance Criteria:**
- Если OpenCode успешно вернул ответ — отчёт содержит: краткое резюме (сколько совпадений по логам), блок с предложениями OpenCode, при необходимости усечённый сырой вывод логов (если помещается в лимит Telegram)
- Если OpenCode недоступен или не сработал — отчёт содержит только сырой вывод логов с пометкой, что AI-анализ не выполнен
- Длина сообщения не превышает лимит Telegram (4096 символов); при переполнении — обрезать с пометкой «… (обрезано)» или разбить на несколько сообщений (конкретизировать в дизайне)

### REQ-017-6: Отправка отчёта администратору
Отправить сформированный отчёт в Telegram получателю из конфига.

**Acceptance Criteria:**
- Получатель: `admin_id` из секции `[reports]` в settings.toml (тот же, что для черновика отчётов и бэкапов)
- Отправка через `bot.send_message(chat_id=admin_id, text=report_text)`
- Если `admin_id = 0` или не указан — отчёт не отправляется (только сохранение файла выгрузки и при возможности OpenCode-анализ в лог/файл — опционально)
- Ошибки отправки логировать через structlog, не крашить бота

### REQ-017-7: Расписание и конфигурация
Задача выполняется по расписанию раз в сутки; время анализа логов задаётся вручную в настройках.

**Acceptance Criteria:**
- Запуск по расписанию через APScheduler (cron); время запуска джобы настраивается (например `hour`, `minute` в timezone из `[reports]`; по умолчанию 00:30)
- Временное окно логов задаётся вручную: `log_since`, `log_until` в `[code_quality_report]` (см. REQ-017-1)
- В конфиге предусмотреть: `enabled`, `hour`, `minute`, `log_since`, `log_until`, `container_name`, `grep_pattern`, `output_dir`, `opencode_timeout_seconds`, `max_extra_log_requests`, `max_extra_log_bytes`
- Если `enabled = false` — джобу не регистрировать

---

## 🎯 Goals

**Primary Goal:**  
Раз в сутки (по расписанию) собирать логи приложения из Docker за заданное вручную временное окно (ошибки/предупреждения по фильтру), при необходимости давать агенту возможность довыгружать полные логи для контекста, анализировать через OpenCode CLI и отправлять администратору отчёт с предложениями по улучшению/исправлению.

**Why This Matters:**
- Видимость ошибок и предупреждений из рантайма без ручного просмотра логов
- Время анализа задаётся вручную — гибкость (например «вчера 15:40–17:27»)
- Агент может запросить полные логи по нужному интервалу для полной картины
- Единая точка доставки отчёта — Telegram админу (как для draft report и бэкапов)

**Use Cases:**
1. Админ задаёт в конфиге `log_since = "2026-02-16T15:40:00"`, `log_until = "2026-02-16T17:27:00"`; утром получает отчёт по логам за этот интервал с предложениями OpenCode.
2. OpenCode запрашивает довыгрузку логов за 15:40–15:45 без фильтра — сервис выполняет `docker logs ... --since ... --until ...`, добавляет к контексту и повторяет анализ.
3. OpenCode не установлен — админ получает только сырой вывод `docker logs ... | grep ...`.
4. Админ отключает отправку (`admin_id = 0`) — выгрузка и анализ выполняются локально, отчёт не отправляется.

---

## 📐 Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              APScheduler (cron: daily, e.g. 00:30)               │
│  Time window for logs: from config log_since / log_until          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│         CodeQualityReportService.collect_docker_logs()            │
│  1. docker logs <container> --since <log_since> --until <log_until> │
│     2>&1 | grep -E "<grep_pattern>" -i                           │
│  2. Write to output_dir/code_quality_YYYYMMDD_HHMMSS.txt         │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│         CodeQualityReportService.run_opencode_analysis()          │
│  1. opencode run "<prompt>" --file <path> (with timeout)          │
│  2. Parse response for REQUEST_LOGS: <since> <until>             │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│         CodeQualityReportService.fetch_extra_logs()              │
│  1. For each REQUEST_LOGS: docker logs --since X --until Y 2>&1   │
│     (no grep); append to context; cap by max_extra_log_requests   │
│     and max_extra_log_bytes                                       │
│  2. Re-run opencode with combined context → final AI report       │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│         CodeQualityReportService.build_report()                   │
│  1. If AI text present: summary + AI block + optional raw tail   │
│  2. Else: raw log output + note "AI analysis skipped"             │
│  3. Truncate to 4096 or split to multiple messages               │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│         CodeQualityReportService.send_to_admin()                 │
│  1. Get admin_id from [reports]; if 0 → skip                      │
│  2. Else: bot.send_message(admin_id, report_text)                 │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
bot/
└── services/
    └── code_quality_report.py   # CodeQualityReportService

# Config: [code_quality_report] in settings.toml (and existing [reports].admin_id)
# Output (optional): e.g. /tmp/casino_code_quality/code_quality_YYYYMMDD_HHMMSS.txt
```

### Configuration (settings.toml)

```toml
[reports]
timezone = "Asia/Yekaterinburg"
admin_id = 123456789   # Recipient for code quality report too

[code_quality_report]
enabled = true
# When to run the job (in reports.timezone)
hour = 0
minute = 30
# Time window for logs — set manually (ISO 8601 or relative like "24h" / "now")
log_since = "2026-02-16T15:40:00"
log_until = "2026-02-16T17:27:00"
# Docker container to fetch logs from
container_name = "python-runner"
# Grep pattern for filtering (default: (warning|error|Error|Exception))
grep_pattern = "(warning|error|Error|Exception)"
# Directory to store raw log output (default /tmp/casino_code_quality)
output_dir = "/tmp/casino_code_quality"
# OpenCode
opencode_timeout_seconds = 120
# Limits for agent-requested extra log fetches
max_extra_log_requests = 3
max_extra_log_bytes = 102400
# Optional: also include ruff/pyright output in the same artifact (default false)
# include_lint_output = false
```

### OpenCode CLI contract

- **Command:** `opencode run "<prompt>" --file <path_to_log_output>`
- **Prompt:** явно указать: 1) это вывод `docker logs`, отфильтрованный по ошибкам/предупреждениям; 2) если нужен полный контекст по какому-то интервалу, вывести строку(и) в формате `REQUEST_LOGS: <since_iso> <until_iso>` (один запрос на строку); 3) затем дать краткий отчёт на русском: количество совпадений, предложения по исправлению/улучшению; ответ до 3000 символов.
- **Second pass:** если в выводе OpenCode найдены строки `REQUEST_LOGS: ...`, для каждой (с учётом лимитов) выполнить `docker logs <container> --since <since> --until <until> 2>&1` без grep, добавить к контексту и перезапустить OpenCode с объединённым файлом для финального отчёта.
- **Timeout:** из конфига `opencode_timeout_seconds`
- **Detection:** проверка наличия `opencode` в PATH; при отсутствии — fallback без AI.

### Telegram message limit

- Один текст сообщения — до 4096 символов. При превышении: либо обрезать с пометкой «(обрезано)», либо отправить два сообщения (первое — резюме + AI, второе — сырой вывод).

### Error handling

- Любая ошибка внутри джобы (сбор вывода, opencode, отправка) логируется, бот не падает.
- Если отправка админу не удалась — залогировать и оставить файл выгрузки на диске.

---

## 📎 Out of scope (explicitly)

- Запуск линтеров (ruff/pyright) в эту выгрузку — опционально через `include_lint_output`; по умолчанию только Docker-логи.
- Изменение кода по предложениям OpenCode (только отчёт, решения принимает человек).
- Обязательная установка OpenCode на сервере (опционально; без него — только сырой вывод логов).
- Запуск `docker logs` с хоста, если бот работает внутри Docker: предполагается, что либо бот на хосте, либо доступ к Docker socket/API настроен (реализация — в коде).

---

## 📚 References

- Docker logs: `docker logs <container> --since "<iso>" --until "<iso>" 2>&1 | grep -E "..." -i`
- OpenCode CLI: https://opencode.ai/docs/cli (`opencode run`, `--file`)
- `bot/__main__.py` — регистрация cron-джоб, `reports_config.timezone`, `reports_config.admin_id`
- `bot/config_reader.py` — `ReportsConfig.admin_id`
- TASK-015 — джоба по расписанию, отправка админу, конфиг
