# TASK-020: Command contract cleanup

**ID**: TASK-020  
**Title**: Очистка командного контракта Left4Casino от legacy fork-текстов  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-05-10  
**Assignee**: cursor-agent

---

## Контекст

В интерфейсе бота остались тексты и меню из исходного casino demo fork: `/start` рекламировал reply keyboard и `/spin`, `/help` ссылался на MasterGroosha/GitHub, а Bot API menu показывал команды, не соответствующие текущему групповому Left4Casino flow.

TASK-020 фиксирует минимальный безопасный контракт без изменения game balance, БД-схемы, stage/prod окружений и runtime-конфигов.

---

## Requirements

### REQ-020-1: Neutral `/start`

`/start` должен оставаться безопасным entrypoint, но не должен отправлять legacy casino demo text, ссылки fork, `/spin` hints или reply keyboard.

**Acceptance Criteria:**
- Пользователь по-прежнему создаётся/синхронизируется в БД, если текущий handler это делает.
- Ответ нейтральный, Left4Casino-specific, указывает что бот работает в группах и направляет к `/help`.
- `ReplyKeyboardMarkup` не отправляется из `/start`.

### REQ-020-2: Current `/help` and locale contract

Тексты справки должны описывать текущие команды Left4Casino.

**Acceptance Criteria:**
- `/help` перечисляет `/balance`, `/bid`, `/safe`, `/stats`, `/top`, `/give`, `/credit`, `/dice`, `/take` и слоты через Telegram 🎰 dice.
- Удалены old fork/GitHub/demo/MasterGroosha references из current/example locale-файлов.
- `/stop` сохраняется только как cleanup старых клавиатур и не рекламирует `/spin`.

### REQ-020-3: Group Bot API menu

Bot API command menu должен рекламировать только реально поддерживаемые групповые команды.

**Acceptance Criteria:**
- Group menu содержит `/balance`, `/bid`, `/safe`, `/stats`, `/top`, `/dice`, `/take`, `/give`, `/credit`, `/help`.
- `/start`, `/spin`, `/stop` не рекламируются.
- Default/private menu scopes очищаются по возможности без логирования токенов.
- Unit-тесты фиксируют scope и список команд.

### REQ-020-4: E2E contract checks

TASK-019 stage parity/menu checks должны ловить stale `/start`/keyboard/menu regressions.

**Acceptance Criteria:**
- Stage parity rejects old `/start` text, `/spin` hints, fork links and reply keyboards.
- Optional stage menu validation checks group command scope and rejects stale advertised commands.

---

## Testing & Validation

- Targeted pytest for handlers, UI command menu and E2E smoke helpers.
- Full `./scripts/test.sh`.
- Full `./scripts/lint.sh`.

---

## Out of Scope

- Production/stage runtime changes.
- `settings.toml`, `.env`, SQLite DB mutation.
- Removing the existing keyboard helper if still used by legacy `/spin` tests/handler.
