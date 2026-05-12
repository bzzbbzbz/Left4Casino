# TASK-023 — Daily Report E2E Manual Trigger

## Status

SPEC_READY

## Problem

Stage E2E покрывает команды, экономику, `/credit`, Happy Moment и Heist, но не проверяет ручной запуск ежедневных итогов дня. Из-за этого можно сломать `DailyStatsService`, формат отчёта или агрегацию `event_history`, а текущие live E2E этого не поймают.

## Goal

Добавить stage-only E2E проверку ручного вызова daily report, чтобы убедиться, что итоги дня считаются и отправляются корректно до production rollout.

## Requirements

- REQ-023-1: Добавить безопасный stage-only способ вызвать daily report вручную из live stage bot process.
- REQ-023-2: Вызов должен быть закрыт теми же guard-подходами, что event E2E hooks: disabled by default, explicit env enable, allowed user id.
- REQ-023-3: E2E должен подготовить минимальные stage DB события для tester/chat под `TELEGRAM_E2E_ALLOW_DB_MUTATION=1` или использовать уже имеющиеся stage events без мутации, если это достаточно надёжно.
- REQ-023-4: E2E должен проверить Telegram-visible report message и ключевые DB-derived показатели: wins/losses, total_won/total_lost, bankruptcies, credits/transfers/events where applicable.
- REQ-023-5: Production E2E не должен мутировать prod DB и не должен включать stage-only hooks.
- REQ-023-6: Документировать команды запуска и добавить unit-тесты fake API/DB для runner logic.

## Suggested Scenario

`TELEGRAM_E2E_SCENARIO=daily-report`

Required env:

```bash
TELEGRAM_E2E_ALLOW_DB_MUTATION=1
TELEGRAM_E2E_ALLOW_DAILY_REPORT_HOOK=1
LEFT4CASINO_E2E_HOOKS_ENABLED=1
LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID=<tester_bot_user_id>
```

## Acceptance Criteria

- `./scripts/test.sh tests/unit/test_telegram_e2e_smoke.py` passes.
- `./scripts/test.sh` passes.
- `./scripts/lint.sh` passes.
- Live stage `daily-report` E2E passes sequentially in the dedicated stage chat.
- Strict `schedule-readiness` remains green after the daily report E2E run.
