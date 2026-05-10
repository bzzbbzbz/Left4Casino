# TASK-021: Event E2E coverage and `/start` removal

**ID**: TASK-021  
**Title**: Удаление `/start` и обязательное live E2E покрытие Happy Moment/Heist на stage  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-05-10  
**Assignee**: cursor-agent

---

## Context

После TASK-020 `/start` больше не должен быть entrypoint: команда не должна регистрировать игрока, отвечать или отправлять клавиатуру. Одновременно критичные live events (Happy Moment и Heist) требуют stage-only E2E проверки через реальный процесс бота, чтобы slot spins видели активное состояние сервисов.

---

## Requirements

### REQ-021-1: `/start` absent/unhandled

- Удалить обработчик `/start` из default router.
- Удалить неиспользуемые `start-text` locale keys.
- Smoke/stage-parity E2E не должны посылать `/start` как обычный шаг.
- Stage-parity должен проверять, что `/start@StageBot` не получает ответа от stage bot и не приносит `reply_markup`, затем `/balance` всё ещё отвечает.

### REQ-021-2: Stage-only E2E hooks

- Добавить скрытый router с командами `/e2e_happy_start`, `/e2e_happy_end`, `/e2e_heist_start`, `/e2e_heist_end`.
- Router включается только при `LEFT4CASINO_E2E_HOOKS_ENABLED=1/true` и обязательном валидном `LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID`.
- Если caller guard отсутствует/невалиден, hooks fail-closed: router не регистрируется, а handler-level guard также отказывает.
- Hook start не заменяет реальные активные Happy Moment/Heist: non-E2E active event получает отказ без мутации. Перезапуск/cleanup допускается только для E2E-owned state.
- Hooks не добавляются в Bot API menu и не меняют production scheduler.

### REQ-021-3: Live event E2E scenario

- Добавить сценарий `events`/`event-flows`, требующий `TELEGRAM_E2E_ALLOW_EVENT_HOOKS=1` и `TELEGRAM_E2E_ALLOW_DB_MUTATION=1`.
- Сценарий должен preflight/drain updates, сбрасывать тестовый баланс, запускать Happy Moment hook, крутить слоты до `happy_moment_win`, завершать Happy Moment, запускать Heist hook, крутить до `heist_contribution` + `loss(during_heist=true)`, завершать Heist и проверять DB events/metadata.
- Все DB paths проходят stage-prefix guard; tokens остаются redacted.
- Failure cleanup отправляет end-hooks, ждёт stage-bot ack и сообщает cleanup failure в ошибке сценария.

### REQ-021-4: Tests and validation

- Unit/integration tests фиксируют отсутствие `/start`, negative wait stage-parity, opt-in guards, metadata assertions and E2E hook guards.
- Полная валидация: targeted pytest, `./scripts/test.sh`, `./scripts/lint.sh`.

---

## Result

TASK-021 выполнена и заархивирована без изменения production, `/opt` stage, secrets, `settings.toml`, SQLite DBs или untracked credential helper files.
