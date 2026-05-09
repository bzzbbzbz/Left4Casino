# Autonomous Backlog Execution Agreement

Date: 2026-05-09

This document records the agreed execution rules for closing the active backlog. It intentionally does not contain secrets, bot tokens, API keys, chat IDs that are not already public in configuration, or production credentials.

## Execution Mode

- The assistant may work autonomously across the remaining backlog using subagents for focused research, implementation checks, DevOps analysis, and verification.
- The assistant may create branches, commits, pushes, and pull requests without asking for approval for every individual step.
- The assistant must keep the high-level context, sequencing, safety rules, and final integration decisions centralized in the main orchestration thread.
- The assistant may use separate commits per task or per atomic implementation unit.

## Task Order

The agreed order is:

1. `TASK-015` Automated Daily Backups.
2. `TASK-017` Daily Code Quality Report.
3. `TASK-016` Big Integer Money Storage for `10^24+` balances.
4. `TASK-019` Telegram bot-to-bot E2E smoke tester for staging.

`TASK-019` is planned now rather than left as distant backlog, because it will help validate `TASK-016` on staging before production rollout.

## Production Safety

- Do not modify production runtime without explicit approval.
- Do not restart production Docker/container without explicit approval.
- Do not run schema/data migrations against production DB without explicit approval.
- First validate changes on staging.
- Production currently remains Docker-based; do not migrate production to systemd unless explicitly requested.

## Rollback Model

- Code rollback is via git: revert commits, redeploy a previous commit, or reset a non-production worktree.
- SQLite data rollback is not covered by git. DB rollback requires a filesystem backup created before migration or risky operations.
- `TASK-016` must be tested on a copied DB mounted into staging before any production migration.

## TASK-015 Decisions

- Local backup directory: `/tmp/casino_backups`.
- Send backup archive to the configured admin via Telegram when `admin_id` is configured.
- Backup implementation may use the safest available local mechanism. Prefer SQLite Online Backup API when feasible; fallback behavior must be explicit and tested.

## TASK-017 Decisions

- Run real `opencode` CLI when available.
- Analyze Docker logs from the `python-runner` container.
- The service may read Docker logs in the configured runtime environment.
- If `opencode` or Docker log access fails, the bot must not crash; the report should include a clear fallback note.

## TASK-016 Decisions

- Use the updated exact big-int storage contract: SQLite `TEXT` for persisted money, Python `int` in code.
- Do not use scale factor or SQLite `REAL` for money.
- Copy `casino.db` and mount/use the copy in staging for migration validation before production.
- Validate with automated tests and later with `TASK-019` live smoke before any production migration.

## TASK-019 Decisions

- Tester bot username: `@e2ecasinoqabot`.
- Tester bot token must be provided via environment/config outside git.
- Stage chat is the group named `test`; exact chat ID should be discovered from configured `allowed_chat_ids` or runtime updates.
- Stage bot and tester bot are already added to the staging group.
- Bot-to-Bot Communication Mode must be enabled in BotFather for the participating bots.
- The tester must use loop prevention: max steps, timeouts, dedupe, and rate limits.

## Secret Handling

- Never commit real bot tokens, API keys, `.env` files, `settings.toml`, SQLite DBs, backups, or generated credential update scripts.
- Store tester token in an ignored env file or runtime environment variable, not in tracked documentation.
- If a token is accidentally exposed in a tracked file, rotate it immediately before proceeding.
