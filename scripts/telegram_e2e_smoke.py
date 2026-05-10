#!/usr/bin/env python3
"""TASK-019 Telegram bot-to-bot smoke runner for the staging bot.

The runner is intentionally opt-in and env-only: it never reads real bot tokens
from project config files and validates that SQLite paths point at staging before
any scenario messages are sent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
import tomllib
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bot.money import decode_money

ENV_TESTER_TOKEN = "TELEGRAM_E2E_TESTER_TOKEN"
ENV_STAGE_BOT_USERNAME = "TELEGRAM_E2E_STAGE_BOT_USERNAME"
ENV_STAGE_SETTINGS_PATH = "TELEGRAM_E2E_STAGE_SETTINGS_PATH"
ENV_STAGE_DB_PATH = "TELEGRAM_E2E_STAGE_DB_PATH"
ENV_TARGET_CHAT_ID = "TELEGRAM_E2E_TARGET_CHAT_ID"
ENV_TIMEOUT = "TELEGRAM_E2E_TIMEOUT_SECONDS"
ENV_RATE_LIMIT = "TELEGRAM_E2E_RATE_LIMIT_SECONDS"
ENV_MAX_STEPS = "TELEGRAM_E2E_MAX_STEPS"
ENV_DRY_RUN = "TELEGRAM_E2E_DRY_RUN"
ENV_ALLOWED_DB_PREFIX = "TELEGRAM_E2E_ALLOWED_DB_PREFIX"

DEFAULT_STAGE_PREFIX = "/opt/left4casino/python-runner-stage"
DEFAULT_PROD_DB_PATHS = {
    Path("/root/n8n-install/python-runner/telegram-casino-bot/bot/casino.db"),
    Path("/root/n8n-install/python-runner/bot/casino.db"),
}


class ConfigError(ValueError):
    """Raised when E2E configuration is unsafe or incomplete."""


class SmokeFailureError(AssertionError):
    """Raised when the smoke scenario or DB assertions fail."""


@dataclass(frozen=True)
class E2EConfig:
    tester_token: str
    stage_bot_username: str
    stage_settings_path: Path
    stage_db_path: Path
    target_chat_id: int | None
    timeout_seconds: float = 30.0
    rate_limit_seconds: float = 1.0
    max_steps: int = 30
    dry_run: bool = False
    allowed_db_prefix: Path = Path(DEFAULT_STAGE_PREFIX)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> E2EConfig:
        env = dict(os.environ if env is None else env)
        token = _required(env, ENV_TESTER_TOKEN)
        username = _normalize_username(_required(env, ENV_STAGE_BOT_USERNAME))
        settings_path = Path(_required(env, ENV_STAGE_SETTINGS_PATH)).expanduser()
        db_path = Path(_required(env, ENV_STAGE_DB_PATH)).expanduser()
        target_chat_id = _optional_int(env.get(ENV_TARGET_CHAT_ID), ENV_TARGET_CHAT_ID)
        timeout = _optional_float(env.get(ENV_TIMEOUT), ENV_TIMEOUT, default=30.0)
        rate_limit = _optional_float(env.get(ENV_RATE_LIMIT), ENV_RATE_LIMIT, default=1.0)
        max_steps = _optional_int(env.get(ENV_MAX_STEPS), ENV_MAX_STEPS) or 30
        dry_run = _parse_bool(env.get(ENV_DRY_RUN, "false"))
        allowed_prefix = Path(env.get(ENV_ALLOWED_DB_PREFIX, DEFAULT_STAGE_PREFIX)).expanduser()
        if timeout <= 0:
            raise ConfigError(f"{ENV_TIMEOUT} must be > 0")
        if rate_limit < 0:
            raise ConfigError(f"{ENV_RATE_LIMIT} must be >= 0")
        if max_steps <= 0:
            raise ConfigError(f"{ENV_MAX_STEPS} must be > 0")
        return cls(
            tester_token=token,
            stage_bot_username=username,
            stage_settings_path=settings_path,
            stage_db_path=db_path,
            target_chat_id=target_chat_id,
            timeout_seconds=timeout,
            rate_limit_seconds=rate_limit,
            max_steps=max_steps,
            dry_run=dry_run,
            allowed_db_prefix=allowed_prefix,
        )

    def redacted(self) -> dict[str, Any]:
        data = asdict(self)
        data["tester_token"] = "<redacted>"
        data["stage_settings_path"] = str(self.stage_settings_path)
        data["stage_db_path"] = str(self.stage_db_path)
        data["allowed_db_prefix"] = str(self.allowed_db_prefix)
        return data


@dataclass(frozen=True)
class SafeStageSettings:
    allowed_chat_ids: tuple[int, ...]
    block_private_chats: bool | None


@dataclass(frozen=True)
class PreflightResult:
    target_chat_id: int
    tester_bot_id: int
    tester_username: str
    stage_bot_id: int
    stage_bot_username: str
    chat_title: str | None


@dataclass
class ScenarioStep:
    name: str
    action: str
    text: str | None = None
    emoji: str | None = None


@dataclass
class SmokeReport:
    ok: bool
    config: dict[str, Any]
    preflight: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    db_assertions: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


class BotApiProtocol(Protocol):
    async def get_me(self) -> dict[str, Any]: ...

    async def get_chat(self, chat_id: int | str) -> dict[str, Any]: ...

    async def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]: ...

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]: ...

    async def send_dice(self, chat_id: int, emoji: str) -> dict[str, Any]: ...

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0, allowed_updates: list[str] | None = None
    ) -> list[dict[str, Any]]: ...


class TelegramBotApi:
    def __init__(self, token: str) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}/"

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._call_sync, method, payload or {})

    def _call_sync(self, method: str, payload: dict[str, Any]) -> Any:
        data = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(self._base_url + method, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode())
        if not body.get("ok"):
            raise SmokeFailureError(f"Bot API {method} failed: {body.get('description', body)}")
        return body.get("result")

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return await self._call("getChat", {"chat_id": chat_id})

    async def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        return await self._call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        return await self._call("sendMessage", {"chat_id": chat_id, "text": text})

    async def send_dice(self, chat_id: int, emoji: str) -> dict[str, Any]:
        return await self._call("sendDice", {"chat_id": chat_id, "emoji": emoji})

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0, allowed_updates: list[str] | None = None
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = json.dumps(allowed_updates)
        return await self._call("getUpdates", payload)


class StageReplyFilter:
    def __init__(self, *, stage_bot_username: str, stage_bot_id: int | None = None) -> None:
        self.stage_bot_username = _normalize_username(stage_bot_username).lower()
        self.stage_bot_id = stage_bot_id
        self.seen_update_ids: set[int] = set()
        self.seen_message_keys: set[tuple[int, int]] = set()

    def filter_new(self, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                if update_id in self.seen_update_ids:
                    continue
                self.seen_update_ids.add(update_id)
            message = update.get("message") or update.get("edited_message")
            if not isinstance(message, dict):
                continue
            if not self._from_stage_bot(message):
                continue
            chat_id = _deep_get(message, "chat", "id")
            message_id = message.get("message_id")
            if isinstance(chat_id, int) and isinstance(message_id, int):
                key = (chat_id, message_id)
                if key in self.seen_message_keys:
                    continue
                self.seen_message_keys.add(key)
            accepted.append(message)
        return accepted

    def _from_stage_bot(self, message: dict[str, Any]) -> bool:
        sender = message.get("from")
        if not isinstance(sender, dict):
            return False
        if self.stage_bot_id is not None and sender.get("id") == self.stage_bot_id:
            return True
        username = sender.get("username")
        return isinstance(username, str) and username.lower() == self.stage_bot_username


def parse_safe_stage_settings(settings_path: Path) -> SafeStageSettings:
    if not settings_path.exists():
        raise ConfigError(f"stage settings file does not exist: {settings_path}")
    with settings_path.open("rb") as handle:
        data = tomllib.load(handle)
    restrictions = data.get("chat_restrictions")
    if not isinstance(restrictions, dict):
        raise ConfigError("stage settings must contain [chat_restrictions]")
    raw_ids = restrictions.get("allowed_chat_ids", [])
    if not isinstance(raw_ids, list):
        raise ConfigError("chat_restrictions.allowed_chat_ids must be a list")
    allowed_chat_ids = tuple(_coerce_int(value, "allowed_chat_ids") for value in raw_ids)
    block_private = restrictions.get("block_private_chats")
    if block_private is not None and not isinstance(block_private, bool):
        raise ConfigError("chat_restrictions.block_private_chats must be boolean when set")
    return SafeStageSettings(allowed_chat_ids=allowed_chat_ids, block_private_chats=block_private)


def resolve_target_chat_id(config: E2EConfig, settings: SafeStageSettings) -> int:
    allowed = settings.allowed_chat_ids
    if not allowed:
        if config.target_chat_id is None:
            raise ConfigError(f"{ENV_TARGET_CHAT_ID} is required when no allowed_chat_ids exist")
        return config.target_chat_id
    if len(allowed) > 1 and config.target_chat_id is None:
        raise ConfigError(f"{ENV_TARGET_CHAT_ID} is required when multiple allowed_chat_ids exist")
    target_chat_id = config.target_chat_id if config.target_chat_id is not None else allowed[0]
    if target_chat_id not in allowed:
        raise ConfigError(f"target chat id {target_chat_id} is not in stage allowed_chat_ids")
    return target_chat_id


def validate_stage_db_path(db_path: Path, allowed_prefix: Path) -> Path:
    resolved_db = db_path.resolve(strict=False)
    resolved_prefix = allowed_prefix.resolve(strict=False)
    if resolved_db in DEFAULT_PROD_DB_PATHS:
        raise ConfigError(f"refusing default/prod database path: {resolved_db}")
    if any(_is_prod_path_component(part) for part in resolved_db.parts):
        raise ConfigError(f"refusing database path with prod component: {resolved_db}")
    try:
        resolved_db.relative_to(resolved_prefix)
    except ValueError as exc:
        raise ConfigError(
            f"database path {resolved_db} is outside allowed prefix {resolved_prefix}"
        ) from exc
    if resolved_db.suffix != ".db":
        raise ConfigError("stage database path must point to a .db file")
    return resolved_db


def _is_prod_path_component(part: str) -> bool:
    normalized = part.lower()
    return normalized in {"prod", "production"} or normalized.endswith("-prod")


async def run_preflight(config: E2EConfig, api: BotApiProtocol) -> PreflightResult:
    settings = parse_safe_stage_settings(config.stage_settings_path)
    target_chat_id = resolve_target_chat_id(config, settings)
    validate_stage_db_path(config.stage_db_path, config.allowed_db_prefix)

    tester = await api.get_me()
    tester_id = _coerce_int(tester.get("id"), "getMe.id")
    tester_username = str(tester.get("username") or "")
    stage_chat = await api.get_chat(target_chat_id)
    stage_bot = await api.get_chat(f"@{config.stage_bot_username}")
    stage_bot_id = _coerce_int(stage_bot.get("id"), "stage bot id")
    await api.get_chat_member(target_chat_id, tester_id)
    await api.get_chat_member(target_chat_id, stage_bot_id)
    stage_username = str(stage_bot.get("username") or config.stage_bot_username)
    if _normalize_username(stage_username).lower() != config.stage_bot_username.lower():
        raise ConfigError("getChat stage bot username does not match configured username")
    return PreflightResult(
        target_chat_id=target_chat_id,
        tester_bot_id=tester_id,
        tester_username=tester_username,
        stage_bot_id=stage_bot_id,
        stage_bot_username=_normalize_username(stage_username),
        chat_title=stage_chat.get("title"),
    )


def build_smoke_steps(stage_bot_username: str) -> list[ScenarioStep]:
    suffix = f"@{_normalize_username(stage_bot_username)}"
    return [
        ScenarioStep("start", "message", f"/start{suffix}"),
        ScenarioStep("balance", "message", f"/balance{suffix}"),
        ScenarioStep("bid", "message", f"/bid{suffix} 1"),
        ScenarioStep("safe", "message", f"/safe{suffix}"),
        ScenarioStep("slots", "dice", emoji="🎰"),
        ScenarioStep("stats", "message", f"/stats{suffix}"),
        ScenarioStep("top", "message", f"/top{suffix}"),
    ]


async def run_scenario(
    config: E2EConfig, api: BotApiProtocol, preflight: PreflightResult
) -> list[dict[str, Any]]:
    steps = build_smoke_steps(config.stage_bot_username)
    if len(steps) > config.max_steps:
        raise ConfigError("scenario step count exceeds configured max steps")
    reply_filter = StageReplyFilter(
        stage_bot_username=preflight.stage_bot_username, stage_bot_id=preflight.stage_bot_id
    )
    update_offset: int | None = None
    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if index > config.max_steps:
            raise SmokeFailureError("max steps exceeded")
        sent: dict[str, Any] | None = None
        dice_before: dict[str, Any] | None = None
        db_validated = False
        if config.dry_run:
            sent = {"dry_run": True, "text": step.text, "emoji": step.emoji}
            replies: list[dict[str, Any]] = []
        else:
            if step.action == "dice":
                dice_before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
            if step.action == "message" and step.text is not None:
                sent = await api.send_message(preflight.target_chat_id, step.text)
            elif step.action == "dice" and step.emoji is not None:
                sent = await api.send_dice(preflight.target_chat_id, step.emoji)
            else:
                raise SmokeFailureError(f"invalid scenario step: {step}")
            await asyncio.sleep(config.rate_limit_seconds)
            replies, update_offset = await poll_stage_replies(
                api=api,
                reply_filter=reply_filter,
                update_offset=update_offset,
                timeout_seconds=config.timeout_seconds,
            )
            if not replies:
                if step.action == "dice" and dice_step_db_changed(
                    config.stage_db_path, preflight.tester_bot_id, dice_before
                ):
                    db_validated = True
                else:
                    raise SmokeFailureError(
                        f"timeout waiting for stage bot reply after step {step.name}"
                    )
        results.append(
            {
                "name": step.name,
                "action": step.action,
                "sent_message_id": sent.get("message_id") if isinstance(sent, dict) else None,
                "reply_count": len(replies),
                "reply_texts": [_message_text(reply) for reply in replies],
                "db_validated": db_validated,
            }
        )
    return results


async def poll_stage_replies(
    *,
    api: BotApiProtocol,
    reply_filter: StageReplyFilter,
    update_offset: int | None,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], int | None]:
    deadline = time.monotonic() + timeout_seconds
    accepted: list[dict[str, Any]] = []
    current_offset = update_offset
    while time.monotonic() < deadline and not accepted:
        updates = await api.get_updates(
            offset=current_offset,
            timeout=min(5, max(0, int(deadline - time.monotonic()))),
            allowed_updates=["message", "edited_message"],
        )
        if updates:
            max_update_id = max(
                update["update_id"]
                for update in updates
                if isinstance(update.get("update_id"), int)
            )
            current_offset = max_update_id + 1
            accepted.extend(reply_filter.filter_new(updates))
        if not accepted:
            await asyncio.sleep(0.25)
    return accepted, current_offset


def snapshot_user_state(db_path: Path, tester_user_id: int) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT user_id, balance, safe_balance, bid FROM users WHERE user_id = ?",
            (tester_user_id,),
        ).fetchone()
        if user is None:
            return None
        event_count = conn.execute(
            "SELECT COUNT(*) FROM event_history WHERE user_id = ?",
            (tester_user_id,),
        ).fetchone()[0]
    return {
        "user_id": user["user_id"],
        "balance": decode_money(user["balance"]),
        "safe_balance": decode_money(user["safe_balance"]),
        "bid": decode_money(user["bid"]),
        "event_count": int(event_count),
    }


def assert_stage_db_state(
    db_path: Path, tester_user_id: int, before: dict[str, Any] | None = None
) -> dict[str, Any]:
    after = snapshot_user_state(db_path, tester_user_id)
    if after is None:
        raise SmokeFailureError(f"tester user {tester_user_id} was not created in stage DB")
    if before is not None:
        if after["balance"] == before["balance"] and after["event_count"] == before["event_count"]:
            raise SmokeFailureError(
                "stage DB did not record balance/event changes for tester scenario"
            )
    elif after["event_count"] <= 0:
        raise SmokeFailureError("stage DB has no event_history rows for tester user")
    return {"before": before, "after": after}


def dice_step_db_changed(db_path: Path, tester_user_id: int, before: dict[str, Any] | None) -> bool:
    """Return True when the dice step visibly mutated the tester's DB state.

    Telegram dice messages may be processed by the stage bot without a bot reply
    being visible to the tester bot.  For dice only, an increased event count or a
    balance change is enough to prove the step was handled.
    """
    after = snapshot_user_state(db_path, tester_user_id)
    if after is None:
        return False
    if before is None:
        return after["event_count"] > 0
    return after["event_count"] > before["event_count"] or after["balance"] != before["balance"]


async def execute(config: E2EConfig, api: BotApiProtocol) -> SmokeReport:
    report = SmokeReport(ok=False, config=config.redacted())
    preflight = await run_preflight(config, api)
    report.preflight = asdict(preflight)
    before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
    report.steps = await run_scenario(config, api, preflight)
    if config.dry_run:
        report.db_assertions = {"skipped": "dry-run sends no scenario messages"}
    else:
        report.db_assertions = assert_stage_db_state(
            config.stage_db_path, preflight.tester_bot_id, before=before
        )
    report.ok = True
    return report


def _required(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or value.strip() == "":
        raise ConfigError(f"missing required env var {name}")
    return value.strip()


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional_int(value: str | None, name: str) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _optional_float(value: str | None, name: str, *, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _coerce_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _normalize_username(username: str) -> str:
    normalized = username.strip().removeprefix("@")
    if not normalized:
        raise ConfigError("stage bot username must not be empty")
    return normalized


def _deep_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _message_text(message: dict[str, Any]) -> str:
    text = message.get("text") or message.get("caption")
    if isinstance(text, str):
        return text
    dice = message.get("dice")
    if isinstance(dice, dict):
        return f"dice:{dice.get('emoji')}={dice.get('value')}"
    return ""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TASK-019 staging Telegram E2E smoke")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=f"Override {ENV_DRY_RUN}=true; preflight only, no scenario messages",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str]) -> int:
    args = parse_args(argv)
    env = dict(os.environ)
    if args.dry_run:
        env[ENV_DRY_RUN] = "true"
    try:
        config = E2EConfig.from_env(env)
        report = await execute(config, TelegramBotApi(config.tester_token))
    except (ConfigError, SmokeFailureError) as exc:
        safe_config: dict[str, Any] = {"error": "configuration not loaded"}
        try:
            safe_config = E2EConfig.from_env(env).redacted()
        except ConfigError:
            pass
        report = SmokeReport(ok=False, config=safe_config, errors=[str(exc)])
        print(report.to_json())
        return 2
    print(report.to_json())
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
