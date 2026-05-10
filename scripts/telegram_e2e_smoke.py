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
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bot.money import decode_money

ENV_TESTER_TOKEN = "TELEGRAM_E2E_TESTER_TOKEN"
ENV_STAGE_BOT_TOKEN = "TELEGRAM_E2E_STAGE_BOT_TOKEN"
ENV_STAGE_BOT_USERNAME = "TELEGRAM_E2E_STAGE_BOT_USERNAME"
ENV_STAGE_SETTINGS_PATH = "TELEGRAM_E2E_STAGE_SETTINGS_PATH"
ENV_STAGE_DB_PATH = "TELEGRAM_E2E_STAGE_DB_PATH"
ENV_TARGET_CHAT_ID = "TELEGRAM_E2E_TARGET_CHAT_ID"
ENV_TIMEOUT = "TELEGRAM_E2E_TIMEOUT_SECONDS"
ENV_RATE_LIMIT = "TELEGRAM_E2E_RATE_LIMIT_SECONDS"
ENV_MAX_STEPS = "TELEGRAM_E2E_MAX_STEPS"
ENV_DRY_RUN = "TELEGRAM_E2E_DRY_RUN"
ENV_ALLOWED_DB_PREFIX = "TELEGRAM_E2E_ALLOWED_DB_PREFIX"
ENV_SCENARIO = "TELEGRAM_E2E_SCENARIO"
ENV_ALLOW_DB_MUTATION = "TELEGRAM_E2E_ALLOW_DB_MUTATION"
ENV_ALLOW_EVENT_HOOKS = "TELEGRAM_E2E_ALLOW_EVENT_HOOKS"
ENV_MAX_SPINS_UNTIL_WIN = "TELEGRAM_E2E_MAX_SPINS_UNTIL_WIN"
ENV_SCHEDULE_STRICT = "TELEGRAM_E2E_SCHEDULE_STRICT"

DEFAULT_STAGE_PREFIX = "/opt/left4casino/python-runner-stage"
DEFAULT_PROD_DB_PATHS = {
    Path("/root/n8n-install/python-runner/telegram-casino-bot/bot/casino.db"),
    Path("/root/n8n-install/python-runner/bot/casino.db"),
}
KNOWN_CREDIT_FALLBACK_TEXTS = {
    "Эй, ты! Хочешь денег? Удиви меня!",
    "Ну что, расскажи анекдот. Живо!",
}


class ConfigError(ValueError):
    """Raised when E2E configuration is unsafe or incomplete."""


class SmokeFailureError(AssertionError):
    """Raised when the smoke scenario or DB assertions fail."""


@dataclass(frozen=True)
class E2EConfig:
    tester_token: str
    stage_bot_token: str | None
    stage_bot_username: str
    stage_settings_path: Path
    stage_db_path: Path
    target_chat_id: int | None
    timeout_seconds: float = 30.0
    rate_limit_seconds: float = 1.0
    max_steps: int = 30
    dry_run: bool = False
    allowed_db_prefix: Path = Path(DEFAULT_STAGE_PREFIX)
    scenario: str = "smoke"
    allow_db_mutation: bool = False
    allow_event_hooks: bool = False
    max_spins_until_win: int = 20
    schedule_strict: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> E2EConfig:
        env = dict(os.environ if env is None else env)
        token = _required(env, ENV_TESTER_TOKEN)
        stage_token = _optional_secret(env.get(ENV_STAGE_BOT_TOKEN))
        username = _normalize_username(_required(env, ENV_STAGE_BOT_USERNAME))
        settings_path = Path(_required(env, ENV_STAGE_SETTINGS_PATH)).expanduser()
        db_path = Path(_required(env, ENV_STAGE_DB_PATH)).expanduser()
        target_chat_id = _optional_int(env.get(ENV_TARGET_CHAT_ID), ENV_TARGET_CHAT_ID)
        timeout = _optional_float(env.get(ENV_TIMEOUT), ENV_TIMEOUT, default=30.0)
        rate_limit = _optional_float(env.get(ENV_RATE_LIMIT), ENV_RATE_LIMIT, default=1.0)
        max_steps = _optional_int(env.get(ENV_MAX_STEPS), ENV_MAX_STEPS) or 30
        dry_run = _parse_bool(env.get(ENV_DRY_RUN, "false"))
        allowed_prefix = Path(env.get(ENV_ALLOWED_DB_PREFIX, DEFAULT_STAGE_PREFIX)).expanduser()
        scenario = env.get(ENV_SCENARIO, "smoke").strip() or "smoke"
        allow_db_mutation = _parse_bool(env.get(ENV_ALLOW_DB_MUTATION, "false"))
        allow_event_hooks = _parse_bool(env.get(ENV_ALLOW_EVENT_HOOKS, "false"))
        max_spins = _optional_int(env.get(ENV_MAX_SPINS_UNTIL_WIN), ENV_MAX_SPINS_UNTIL_WIN) or 20
        schedule_strict = _parse_bool(env.get(ENV_SCHEDULE_STRICT, "false"))
        if timeout <= 0:
            raise ConfigError(f"{ENV_TIMEOUT} must be > 0")
        if rate_limit < 0:
            raise ConfigError(f"{ENV_RATE_LIMIT} must be >= 0")
        if max_steps <= 0:
            raise ConfigError(f"{ENV_MAX_STEPS} must be > 0")
        if max_spins <= 0:
            raise ConfigError(f"{ENV_MAX_SPINS_UNTIL_WIN} must be > 0")
        if scenario not in {
            "smoke",
            "stage-parity",
            "economy",
            "schedule-readiness",
            "events",
            "event-flows",
        }:
            raise ConfigError(f"unsupported scenario: {scenario}")
        return cls(
            tester_token=token,
            stage_bot_token=stage_token,
            stage_bot_username=username,
            stage_settings_path=settings_path,
            stage_db_path=db_path,
            target_chat_id=target_chat_id,
            timeout_seconds=timeout,
            rate_limit_seconds=rate_limit,
            max_steps=max_steps,
            dry_run=dry_run,
            allowed_db_prefix=allowed_prefix,
            scenario=scenario,
            allow_db_mutation=allow_db_mutation,
            allow_event_hooks=allow_event_hooks,
            max_spins_until_win=max_spins,
            schedule_strict=schedule_strict,
        )

    def redacted(self) -> dict[str, Any]:
        data = asdict(self)
        data["tester_token"] = "<redacted>"
        data["stage_bot_token"] = "<redacted>" if self.stage_bot_token else None
        data["stage_settings_path"] = str(self.stage_settings_path)
        data["stage_db_path"] = str(self.stage_db_path)
        data["allowed_db_prefix"] = str(self.allowed_db_prefix)
        return data


@dataclass(frozen=True)
class SafeStageSettings:
    allowed_chat_ids: tuple[int, ...]
    block_private_chats: bool | None
    ai_provider: str


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
    setup_balance: int | None = None


@dataclass
class SmokeReport:
    ok: bool
    config: dict[str, Any]
    preflight: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    db_assertions: dict[str, Any] | None = None
    command_menu: dict[str, Any] | None = None
    schedule_readiness: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


class BotApiProtocol(Protocol):
    async def get_me(self) -> dict[str, Any]: ...

    async def get_chat(self, chat_id: int | str) -> dict[str, Any]: ...

    async def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]: ...

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]: ...

    async def send_dice(self, chat_id: int, emoji: str) -> dict[str, Any]: ...

    async def get_my_commands(
        self, scope: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

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

    async def get_my_commands(self, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {}
        if scope is not None:
            payload["scope"] = json.dumps(scope)
        result = await self._call("getMyCommands", payload)
        if not isinstance(result, list):
            raise SmokeFailureError("Bot API getMyCommands returned non-list result")
        return result

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
    def __init__(
        self,
        *,
        stage_bot_username: str,
        stage_bot_id: int | None = None,
        target_chat_id: int | None = None,
    ) -> None:
        self.stage_bot_username = _normalize_username(stage_bot_username).lower()
        self.stage_bot_id = stage_bot_id
        self.target_chat_id = target_chat_id
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
            if self.target_chat_id is not None and chat_id != self.target_chat_id:
                continue
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
    ai_config = data.get("ai", {})
    ai_provider = "mock"
    if isinstance(ai_config, dict):
        ai_provider = str(ai_config.get("provider") or "mock").strip().lower() or "mock"
    return SafeStageSettings(
        allowed_chat_ids=allowed_chat_ids,
        block_private_chats=block_private,
        ai_provider=ai_provider,
    )


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
        ScenarioStep("balance", "message", f"/balance{suffix}"),
        ScenarioStep("bid", "message", f"/bid{suffix} 1"),
        ScenarioStep("safe", "message", f"/safe{suffix}"),
        ScenarioStep("slots", "dice", emoji="🎰"),
        ScenarioStep("stats", "message", f"/stats{suffix}"),
        ScenarioStep("top", "message", f"/top{suffix}"),
    ]


def build_stage_parity_steps(stage_bot_username: str) -> list[ScenarioStep]:
    suffix = f"@{_normalize_username(stage_bot_username)}"
    return [
        ScenarioStep("start-unhandled", "message_optional_reply", f"/start{suffix}"),
        ScenarioStep("balance", "message", f"/balance{suffix}"),
    ]


def build_economy_steps(stage_bot_username: str, *, include_spin_loop: bool) -> list[ScenarioStep]:
    suffix = f"@{_normalize_username(stage_bot_username)}"
    steps = [
        ScenarioStep("setup-positive-balance", "db_set_balance", setup_balance=50),
        ScenarioStep("bid-all-in", "message", f"/bid{suffix} 999999"),
        ScenarioStep("setup-safe-balance", "db_set_balance", setup_balance=50),
        ScenarioStep("safe-deposit", "message", f"/safe{suffix} 1"),
        ScenarioStep("safe-withdraw", "message", f"/safe{suffix} -1"),
        ScenarioStep("setup-zero-balance", "db_set_balance", setup_balance=0),
        ScenarioStep("credit-entry", "message", f"/credit{suffix}"),
        ScenarioStep("setup-bankruptcy-balance", "db_set_balance", setup_balance=1),
        ScenarioStep("spin-until-bankruptcy", "spin_until_bankruptcy", emoji="🎰"),
    ]
    if include_spin_loop:
        steps.extend(
            [
                ScenarioStep("setup-spin-balance", "db_set_balance", setup_balance=50),
                ScenarioStep("spin-until-win", "spin_until_win", emoji="🎰"),
            ]
        )
    return steps


def build_scenario_steps(config: E2EConfig) -> list[ScenarioStep]:
    if config.scenario == "stage-parity":
        return build_stage_parity_steps(config.stage_bot_username)
    if config.scenario == "economy":
        return build_economy_steps(
            config.stage_bot_username, include_spin_loop=config.max_spins_until_win > 0
        )
    if config.scenario == "schedule-readiness":
        return []
    if config.scenario in {"events", "event-flows"}:
        return []
    return build_smoke_steps(config.stage_bot_username)


async def run_scenario(
    config: E2EConfig, api: BotApiProtocol, preflight: PreflightResult
) -> list[dict[str, Any]]:
    settings = parse_safe_stage_settings(config.stage_settings_path)
    steps = build_scenario_steps(config)
    if len(steps) > config.max_steps:
        raise ConfigError("scenario step count exceeds configured max steps")
    reply_filter = StageReplyFilter(
        stage_bot_username=preflight.stage_bot_username,
        stage_bot_id=preflight.stage_bot_id,
        target_chat_id=preflight.target_chat_id,
    )
    update_offset: int | None = None
    if not config.dry_run:
        update_offset = await drain_current_update_offset(api)
    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if index > config.max_steps:
            raise SmokeFailureError("max steps exceeded")
        sent: dict[str, Any] | None = None
        dice_before: dict[str, Any] | None = None
        credit_before: dict[str, Any] | None = None
        db_validated = False
        db_assertion: dict[str, Any] | None = None
        if config.dry_run:
            sent = {"dry_run": True, "text": step.text, "emoji": step.emoji}
            replies: list[dict[str, Any]] = []
        else:
            if step.action == "db_set_balance":
                if step.setup_balance is None:
                    raise SmokeFailureError(f"missing setup balance for step {step.name}")
                reset_tester_state_for_stage(config, preflight.tester_bot_id, step.setup_balance)
                db_assertion = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
                replies = []
                sent = {"db_mutation": "set_balance"}
                db_validated = True
                results.append(
                    {
                        "name": step.name,
                        "action": step.action,
                        "sent_message_id": None,
                        "reply_count": 0,
                        "reply_texts": [],
                        "db_validated": db_validated,
                        "db_assertion": db_assertion,
                    }
                )
                continue
            if step.action == "dice":
                dice_before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
            if step.action == "spin_until_win":
                result = await run_spin_until_win(
                    config, api, preflight, reply_filter, update_offset
                )
                update_offset = result.pop("update_offset", update_offset)
                results.append(result)
                continue
            if step.action == "spin_until_bankruptcy":
                result = await run_spin_until_bankruptcy(
                    config, api, preflight, reply_filter, update_offset
                )
                update_offset = result.pop("update_offset", update_offset)
                results.append(result)
                continue
            if step.name == "credit-entry":
                credit_before = snapshot_credit_sessions(
                    config.stage_db_path, preflight.tester_bot_id
                )
            if step.action == "message" and step.text is not None:
                sent = await api.send_message(preflight.target_chat_id, step.text)
            elif step.action == "message_optional_reply" and step.text is not None:
                sent = await api.send_message(preflight.target_chat_id, step.text)
            elif step.action == "dice" and step.emoji is not None:
                sent = await api.send_dice(preflight.target_chat_id, step.emoji)
            else:
                raise SmokeFailureError(f"invalid scenario step: {step}")
            await asyncio.sleep(config.rate_limit_seconds)
            poll_timeout = config.timeout_seconds
            if step.name == "start-unhandled":
                poll_timeout = min(config.timeout_seconds, 2.0)
            replies, update_offset = await poll_stage_replies(
                api=api,
                reply_filter=reply_filter,
                update_offset=update_offset,
                timeout_seconds=poll_timeout,
            )
            if step.name == "start-unhandled":
                assert_start_unhandled(replies)
            if not replies:
                if step.action == "message_optional_reply":
                    db_validated = False
                if step.action == "dice" and dice_step_db_changed(
                    config.stage_db_path, preflight.tester_bot_id, dice_before
                ):
                    db_validated = True
                elif step.action != "message_optional_reply":
                    raise SmokeFailureError(
                        f"timeout waiting for stage bot reply after step {step.name}"
                    )
            if step.name == "bid-all-in":
                db_assertion = assert_bid_all_in(config.stage_db_path, preflight.tester_bot_id)
            elif step.name == "safe-deposit":
                db_assertion = assert_safe_balance(
                    config.stage_db_path, preflight.tester_bot_id, expected=1
                )
            elif step.name == "safe-withdraw":
                db_assertion = assert_safe_balance(
                    config.stage_db_path, preflight.tester_bot_id, expected=0
                )
            elif step.name == "credit-entry":
                assert_credit_reply_not_known_fallback(
                    replies,
                    ai_provider=settings.ai_provider,
                )
                db_assertion = assert_credit_session_started(
                    config.stage_db_path, preflight.tester_bot_id, before=credit_before
                )
        results.append(
            {
                "name": step.name,
                "action": step.action,
                "sent_message_id": sent.get("message_id") if isinstance(sent, dict) else None,
                "reply_count": len(replies),
                "reply_texts": [_message_text(reply) for reply in replies],
                "db_validated": db_validated,
                "db_assertion": db_assertion,
            }
        )
    return results


async def drain_current_update_offset(api: BotApiProtocol) -> int | None:
    """Advance past currently pending updates before this E2E run sends steps."""
    current_offset: int | None = None
    for _ in range(10):
        updates = await api.get_updates(
            offset=current_offset,
            timeout=0,
            allowed_updates=["message", "edited_message"],
        )
        update_ids = [
            update["update_id"] for update in updates if isinstance(update.get("update_id"), int)
        ]
        if not update_ids:
            return current_offset
        current_offset = max(update_ids) + 1
        if len(updates) < 100:
            return current_offset
    return current_offset


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
        user_columns = get_table_columns(conn, "users")
        select_columns = "user_id, balance, safe_balance, bid"
        if "bankruptcy_count" in user_columns:
            select_columns += ", bankruptcy_count"
        user = conn.execute(
            f"SELECT {select_columns} FROM users WHERE user_id = ?",
            (tester_user_id,),
        ).fetchone()
        if user is None:
            return None
        event_count = conn.execute(
            "SELECT COUNT(*) FROM event_history WHERE user_id = ?",
            (tester_user_id,),
        ).fetchone()[0]
        bankruptcy_events = conn.execute(
            "SELECT COUNT(*) FROM event_history WHERE user_id = ? AND event_type = 'bankruptcy'",
            (tester_user_id,),
        ).fetchone()[0]
    state = {
        "user_id": user["user_id"],
        "balance": decode_money(user["balance"]),
        "safe_balance": decode_money(user["safe_balance"]),
        "bid": decode_money(user["bid"]),
        "event_count": int(event_count),
        "bankruptcy_events": int(bankruptcy_events),
    }
    if "bankruptcy_count" in user.keys():
        state["bankruptcy_count"] = int(user["bankruptcy_count"] or 0)
    return state


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


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


def stage_parity_db_assertions(
    db_path: Path, tester_user_id: int, before: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return stage-parity DB context without requiring scenario mutation.

    Stage-parity only checks that /start no longer exposes legacy UI and that
    /balance answers in the live stage chat.  Unlike the smoke scenario, those
    commands may legitimately leave the tester's balance and event count
    unchanged, so final DB mutation checks would be a false negative.
    """
    return {
        "skipped": "stage-parity validates command replies without requiring DB mutation",
        "before": before,
        "after": snapshot_user_state(db_path, tester_user_id),
    }


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


def assert_start_unhandled(replies: list[dict[str, Any]]) -> None:
    assert_no_legacy_start_reply(replies)
    if replies:
        raise SmokeFailureError("/start was handled by the stage bot; expected no reply")


def assert_no_legacy_start_reply(replies: list[dict[str, Any]]) -> None:
    legacy_fragments = (
        "добро пожаловать в казино",
        "casino bot",
        "крутите слоты",
        "игровое меню",
        "mastergroosha",
        "github",
        "gitlab",
        "демонстрац",
        "/spin",
    )
    for reply in replies:
        text = _message_text(reply).lower()
        if any(fragment in text for fragment in legacy_fragments):
            raise SmokeFailureError("/start exposed legacy casino welcome text")
        if "reply_markup" in reply:
            raise SmokeFailureError("/start exposed legacy reply keyboard markup")


def set_tester_balance_for_stage(config: E2EConfig, tester_user_id: int, balance: int) -> None:
    reset_tester_state_for_stage(config, tester_user_id, balance)


def reset_tester_state_for_stage(config: E2EConfig, tester_user_id: int, balance: int) -> None:
    if not config.allow_db_mutation:
        raise ConfigError(f"{ENV_ALLOW_DB_MUTATION}=1 is required for DB mutation steps")
    validate_stage_db_path(config.stage_db_path, config.allowed_db_prefix)
    with sqlite3.connect(config.stage_db_path) as conn:
        user_columns = get_table_columns(conn, "users")
        insert_columns = ["user_id", "balance", "safe_balance", "bid"]
        insert_values: list[Any] = [tester_user_id, str(balance), "0", "1"]
        if "state" in user_columns:
            insert_columns.append("state")
            insert_values.append("IDLE")
        update_parts = ["balance = excluded.balance", "safe_balance = '0'", "bid = '1'"]
        if "state" in user_columns:
            update_parts.append("state = 'IDLE'")
        placeholders = ", ".join("?" for _ in insert_columns)
        conn.execute(
            f"""
            INSERT INTO users ({", ".join(insert_columns)})
            VALUES ({placeholders})
            ON CONFLICT(user_id) DO UPDATE SET {", ".join(update_parts)}
            """,
            insert_values,
        )
        if table_exists(conn, "ai_credit_sessions"):
            credit_columns = get_table_columns(conn, "ai_credit_sessions")
            credit_status_column = "status" if "status" in credit_columns else None
            if credit_status_column is None and "state" in credit_columns:
                credit_status_column = "state"
            conn.execute(
                f"""
                UPDATE ai_credit_sessions
                SET {credit_status_column} = 'terminated'
                {", finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP)" if "finished_at" in credit_columns else ""}
                WHERE user_id = ? AND {credit_status_column} IN ('active', 'processing')
                """
                if credit_status_column and "user_id" in credit_columns
                else "SELECT 1 WHERE ? IS NULL",
                (tester_user_id,),
            )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def assert_bid_all_in(db_path: Path, tester_user_id: int) -> dict[str, Any]:
    state = snapshot_user_state(db_path, tester_user_id)
    if state is None:
        raise SmokeFailureError("tester user missing after /bid all-in scenario")
    if state["bid"] != state["balance"]:
        raise SmokeFailureError("/bid above balance did not become all-in")
    return {"bid": state["bid"], "balance": state["balance"]}


def assert_safe_balance(db_path: Path, tester_user_id: int, *, expected: int) -> dict[str, Any]:
    state = snapshot_user_state(db_path, tester_user_id)
    if state is None:
        raise SmokeFailureError("tester user missing after /safe scenario")
    if state["safe_balance"] != expected:
        raise SmokeFailureError(f"expected safe_balance={expected}, got {state['safe_balance']}")
    return {"safe_balance": state["safe_balance"], "balance": state["balance"]}


def snapshot_credit_sessions(db_path: Path, tester_user_id: int) -> dict[str, Any]:
    if not db_path.exists():
        return {"count": 0, "latest_session_id": None, "latest_status": None}
    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "ai_credit_sessions"):
            return {"count": 0, "latest_session_id": None, "latest_status": None}
        columns = get_table_columns(conn, "ai_credit_sessions")
        if "user_id" not in columns:
            raise SmokeFailureError("ai_credit_sessions schema missing required user_id column")
        session_id_expr = "CAST(rowid AS TEXT)"
        for candidate in ("session_id", "id"):
            if candidate in columns:
                session_id_expr = f"CAST({candidate} AS TEXT)"
                break
        status_column = "status" if "status" in columns else "state" if "state" in columns else None
        status_expr = status_column or "NULL"
        order_parts = [
            f"{column} DESC"
            for column in ("created_at", "updated_at", "finished_at")
            if column in columns
        ]
        order_parts.append("rowid DESC")
        count = conn.execute(
            "SELECT COUNT(*) FROM ai_credit_sessions WHERE user_id = ?",
            (tester_user_id,),
        ).fetchone()[0]
        row = conn.execute(
            f"""
            SELECT {session_id_expr}, {status_expr}
            FROM ai_credit_sessions
            WHERE user_id = ?
            ORDER BY {", ".join(order_parts)}
            LIMIT 1
            """,
            (tester_user_id,),
        ).fetchone()
        active_row = None
        if status_column is not None:
            active_order_parts = [
                f"{column} DESC" for column in ("created_at", "updated_at") if column in columns
            ]
            active_order_parts.append("rowid DESC")
            active_row = conn.execute(
                f"""
                SELECT {session_id_expr}, {status_expr}
                FROM ai_credit_sessions
                WHERE user_id = ? AND {status_column} IN ('active', 'processing')
                ORDER BY {", ".join(active_order_parts)}
                LIMIT 1
                """,
                (tester_user_id,),
            ).fetchone()
    return {
        "count": int(count),
        "latest_session_id": row[0] if row else None,
        "latest_status": row[1] if row else None,
        "latest_active_session_id": active_row[0] if active_row else None,
        "latest_active_status": active_row[1] if active_row else None,
        "schema": {
            "session_id_column": "session_id"
            if "session_id" in columns
            else "id"
            if "id" in columns
            else "rowid",
            "status_column": status_column,
            "order_columns": [part.removesuffix(" DESC") for part in order_parts],
        },
    }


def assert_credit_session_started(
    db_path: Path, tester_user_id: int, before: dict[str, Any] | None = None
) -> dict[str, Any]:
    before = before or {"count": 0, "latest_session_id": None, "latest_status": None}
    after = snapshot_credit_sessions(db_path, tester_user_id)
    accepted_statuses = {"active", "processing"}
    if after.get("schema", {}).get("status_column") is None:
        raise SmokeFailureError("ai_credit_sessions schema missing required status column")
    created_new_session = (
        after["count"] > before["count"]
        and after["latest_active_session_id"] != before.get("latest_active_session_id")
        and after["latest_active_status"] in accepted_statuses
    )
    if not created_new_session:
        raise SmokeFailureError("/credit did not create a fresh active AI credit session")
    return {
        "before": before,
        "after": after,
    }


def assert_credit_reply_not_known_fallback(
    replies: list[dict[str, Any]], *, ai_provider: str
) -> None:
    """Non-mock economy E2E must fail if /credit returns a known local fallback task."""
    if ai_provider == "mock":
        return
    reply_texts = {_message_text(reply).strip() for reply in replies}
    fallback_hits = reply_texts.intersection(KNOWN_CREDIT_FALLBACK_TEXTS)
    if fallback_hits:
        raise SmokeFailureError(
            "/credit returned known local fallback text while ai.provider is non-mock"
        )


def assert_bankruptcy_recorded(
    db_path: Path, tester_user_id: int, before: dict[str, Any] | None
) -> dict[str, Any]:
    after = snapshot_user_state(db_path, tester_user_id)
    if after is None:
        raise SmokeFailureError("tester user missing after bankruptcy scenario")
    before_bankruptcy_events = int((before or {}).get("bankruptcy_events", 0))
    after_bankruptcy_events = count_user_events(db_path, tester_user_id, "bankruptcy")
    before_count = int((before or {}).get("bankruptcy_count", 0))
    after_count = int(after.get("bankruptcy_count", before_count))
    if after_bankruptcy_events <= before_bankruptcy_events and after_count <= before_count:
        raise SmokeFailureError("bankruptcy event/count was not recorded")
    return {
        "before_bankruptcy_events": before_bankruptcy_events,
        "after_bankruptcy_events": after_bankruptcy_events,
        "before_bankruptcy_count": before_count,
        "after_bankruptcy_count": after_count,
    }


def count_user_events(db_path: Path, tester_user_id: int, event_type: str) -> int:
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM event_history WHERE user_id = ? AND event_type = ?",
            (tester_user_id, event_type),
        ).fetchone()
    return int(row[0]) if row else 0


async def run_spin_until_win(
    config: E2EConfig,
    api: BotApiProtocol,
    preflight: PreflightResult,
    reply_filter: StageReplyFilter,
    update_offset: int | None,
) -> dict[str, Any]:
    before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
    wins_before = count_user_events(config.stage_db_path, preflight.tester_bot_id, "win")
    current_offset = update_offset
    reply_texts: list[str] = []
    sent_ids: list[int] = []
    for spin in range(1, config.max_spins_until_win + 1):
        sent = await api.send_dice(preflight.target_chat_id, "🎰")
        if isinstance(sent.get("message_id"), int):
            sent_ids.append(sent["message_id"])
        await asyncio.sleep(config.rate_limit_seconds)
        replies, current_offset = await poll_stage_replies(
            api=api,
            reply_filter=reply_filter,
            update_offset=current_offset,
            timeout_seconds=config.timeout_seconds,
        )
        reply_texts.extend(_message_text(reply) for reply in replies)
        after = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
        if after is None:
            continue
        wins_after = count_user_events(config.stage_db_path, preflight.tester_bot_id, "win")
        if wins_after > wins_before or (
            before is not None and after["balance"] > before["balance"]
        ):
            return {
                "name": "spin-until-win",
                "action": "spin_until_win",
                "sent_message_id": sent_ids[-1] if sent_ids else None,
                "reply_count": len(reply_texts),
                "reply_texts": reply_texts,
                "db_validated": True,
                "db_assertion": {
                    "spins": spin,
                    "wins_before": wins_before,
                    "wins_after": wins_after,
                },
                "update_offset": current_offset,
            }
    raise SmokeFailureError(f"no slot win after {config.max_spins_until_win} spins")


async def run_spin_until_bankruptcy(
    config: E2EConfig,
    api: BotApiProtocol,
    preflight: PreflightResult,
    reply_filter: StageReplyFilter,
    update_offset: int | None,
) -> dict[str, Any]:
    before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
    current_offset = update_offset
    reply_texts: list[str] = []
    sent_ids: list[int] = []
    for spin in range(1, config.max_spins_until_win + 1):
        reset_tester_state_for_stage(config, preflight.tester_bot_id, 1)
        sent = await api.send_dice(preflight.target_chat_id, "🎰")
        if isinstance(sent.get("message_id"), int):
            sent_ids.append(sent["message_id"])
        await asyncio.sleep(config.rate_limit_seconds)
        replies, current_offset = await poll_stage_replies(
            api=api,
            reply_filter=reply_filter,
            update_offset=current_offset,
            timeout_seconds=config.timeout_seconds,
        )
        reply_texts.extend(_message_text(reply) for reply in replies)
        try:
            assertion = assert_bankruptcy_recorded(
                config.stage_db_path, preflight.tester_bot_id, before
            )
        except SmokeFailureError:
            continue
        return {
            "name": "spin-until-bankruptcy",
            "action": "spin_until_bankruptcy",
            "sent_message_id": sent_ids[-1] if sent_ids else None,
            "reply_count": len(reply_texts),
            "reply_texts": reply_texts,
            "db_validated": True,
            "db_assertion": {"spins": spin, **assertion},
            "update_offset": current_offset,
        }
    raise SmokeFailureError(f"no bankruptcy after {config.max_spins_until_win} controlled spins")


async def run_event_flows(
    config: E2EConfig, api: BotApiProtocol, preflight: PreflightResult
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not config.allow_event_hooks:
        raise ConfigError(f"{ENV_ALLOW_EVENT_HOOKS}=1 is required for events scenario")
    if not config.allow_db_mutation:
        raise ConfigError(f"{ENV_ALLOW_DB_MUTATION}=1 is required for events scenario")
    suffix = f"@{_normalize_username(preflight.stage_bot_username)}"
    reply_filter = StageReplyFilter(
        stage_bot_username=preflight.stage_bot_username,
        stage_bot_id=preflight.stage_bot_id,
        target_chat_id=preflight.target_chat_id,
    )
    update_offset = await drain_current_update_offset(api)
    steps: list[dict[str, Any]] = []
    assertions: dict[str, Any] = {}
    cleanup_needed = {"happy": False, "heist": False}
    cleanup_errors: list[str] = []
    before_rowid = max_event_rowid(config.stage_db_path)
    try:
        reset_tester_state_for_stage(config, preflight.tester_bot_id, 50)
        await _send_hook_step(
            api,
            reply_filter,
            preflight,
            f"/e2e_happy_start{suffix}",
            "e2e-happy-start",
            config,
            steps,
            update_offset,
            on_sent=lambda: cleanup_needed.__setitem__("happy", True),
        )
        update_offset = steps[-1].pop("update_offset", update_offset)
        happy_start = latest_event_after(config.stage_db_path, "happy_moment_start", before_rowid)
        if happy_start is None:
            raise SmokeFailureError("happy_moment_start event was not recorded")

        happy_result = await run_spin_until_happy_win(
            config, api, preflight, reply_filter, update_offset, before_rowid
        )
        update_offset = happy_result.pop("update_offset", update_offset)
        steps.append(happy_result)
        happy_win = latest_event_after(
            config.stage_db_path,
            "happy_moment_win",
            before_rowid,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        if happy_win is None:
            raise SmokeFailureError("happy_moment_win event was not recorded")
        assert_happy_event_metadata(happy_win)
        if not _reply_or_metadata_has_happy_marker(happy_result["reply_texts"], happy_win):
            raise SmokeFailureError(
                "happy win reply/metadata did not include E2E Happy Moment marker"
            )

        await _send_hook_step(
            api,
            reply_filter,
            preflight,
            f"/e2e_happy_end{suffix}",
            "e2e-happy-end",
            config,
            steps,
            update_offset,
        )
        update_offset = steps[-1].pop("update_offset", update_offset)
        cleanup_needed["happy"] = False

        reset_tester_state_for_stage(config, preflight.tester_bot_id, 50)
        heist_before = max_event_rowid(config.stage_db_path)
        await _send_hook_step(
            api,
            reply_filter,
            preflight,
            f"/e2e_heist_start{suffix}",
            "e2e-heist-start",
            config,
            steps,
            update_offset,
            on_sent=lambda: cleanup_needed.__setitem__("heist", True),
        )
        update_offset = steps[-1].pop("update_offset", update_offset)
        heist_start = latest_event_after(
            config.stage_db_path, "heist_start", heist_before, chat_id=preflight.target_chat_id
        )
        if heist_start is None:
            raise SmokeFailureError("heist_start event was not recorded")

        heist_spin = await run_spin_until_heist_loss(
            config, api, preflight, reply_filter, update_offset, heist_before
        )
        update_offset = heist_spin.pop("update_offset", update_offset)
        steps.append(heist_spin)

        await _send_hook_step(
            api,
            reply_filter,
            preflight,
            f"/e2e_heist_end{suffix}",
            "e2e-heist-end",
            config,
            steps,
            update_offset,
        )
        update_offset = steps[-1].pop("update_offset", update_offset)
        cleanup_needed["heist"] = False

        heist_contribution = latest_event_after(
            config.stage_db_path,
            "heist_contribution",
            heist_before,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        loss = latest_event_after(
            config.stage_db_path,
            "loss",
            heist_before,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        heist_win = latest_event_after(
            config.stage_db_path,
            "heist_win",
            heist_before,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        heist_commission = latest_event_after(
            config.stage_db_path, "heist_commission", heist_before, chat_id=preflight.target_chat_id
        )
        for event_name, event in {
            "heist_contribution": heist_contribution,
            "loss": loss,
            "heist_win": heist_win,
            "heist_commission": heist_commission,
        }.items():
            if event is None:
                raise SmokeFailureError(f"{event_name} event was not recorded")
        assert_heist_event_metadata(heist_contribution, loss, heist_win)
        assertions = {
            "happy_moment_start": happy_start,
            "happy_moment_win": happy_win,
            "heist_start": heist_start,
            "heist_contribution": heist_contribution,
            "heist_loss": loss,
            "heist_win": heist_win,
            "heist_commission": heist_commission,
        }
        return steps, assertions
    except Exception as exc:
        if cleanup_needed["happy"]:
            cleanup_error, update_offset = await _cleanup_hook(
                api=api,
                reply_filter=reply_filter,
                chat_id=preflight.target_chat_id,
                text=f"/e2e_happy_end{suffix}",
                name="cleanup-happy-end",
                config=config,
                update_offset=update_offset,
            )
            if cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cleanup_needed["heist"]:
            cleanup_error, update_offset = await _cleanup_hook(
                api=api,
                reply_filter=reply_filter,
                chat_id=preflight.target_chat_id,
                text=f"/e2e_heist_end{suffix}",
                name="cleanup-heist-end",
                config=config,
                update_offset=update_offset,
            )
            if cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            raise SmokeFailureError(
                f"{exc}; cleanup failures: {'; '.join(cleanup_errors)}"
            ) from exc
        raise


async def _send_hook_step(
    api: BotApiProtocol,
    reply_filter: StageReplyFilter,
    preflight: PreflightResult,
    text: str,
    name: str,
    config: E2EConfig,
    steps: list[dict[str, Any]],
    update_offset: int | None,
    on_sent: Callable[[], None] | None = None,
) -> None:
    sent = await api.send_message(preflight.target_chat_id, text)
    if on_sent is not None:
        on_sent()
    await asyncio.sleep(config.rate_limit_seconds)
    replies, new_offset = await poll_stage_replies(
        api=api,
        reply_filter=reply_filter,
        update_offset=update_offset,
        timeout_seconds=config.timeout_seconds,
    )
    if not replies:
        raise SmokeFailureError(f"timeout waiting for stage bot reply after {name}")
    steps.append(
        {
            "name": name,
            "action": "event_hook",
            "sent_message_id": sent.get("message_id") if isinstance(sent, dict) else None,
            "reply_count": len(replies),
            "reply_texts": [_message_text(reply) for reply in replies],
            "db_validated": True,
            "db_assertion": None,
            "update_offset": new_offset,
        }
    )


async def _cleanup_hook(
    *,
    api: BotApiProtocol,
    reply_filter: StageReplyFilter,
    chat_id: int,
    text: str,
    name: str,
    config: E2EConfig,
    update_offset: int | None,
) -> tuple[str | None, int | None]:
    try:
        await api.send_message(chat_id, text)
        await asyncio.sleep(config.rate_limit_seconds)
        replies, new_offset = await poll_stage_replies(
            api=api,
            reply_filter=reply_filter,
            update_offset=update_offset,
            timeout_seconds=min(config.timeout_seconds, 5.0),
        )
    except Exception as exc:
        return f"{name} send/poll failed: {exc}", update_offset
    if not replies:
        return f"{name} did not receive stage bot ack", new_offset
    reply_texts = [_message_text(reply) for reply in replies]
    expected_marker = _cleanup_success_marker(name)
    if expected_marker and not any(text.startswith(expected_marker) for text in reply_texts):
        return f"{name} received non-success ack: {reply_texts}", new_offset
    return None, new_offset


def _cleanup_success_marker(name: str) -> str | None:
    if "happy" in name:
        return "E2E_HOOK_OK happy_end"
    if "heist" in name:
        return "E2E_HOOK_OK heist_end"
    return None


async def run_spin_until_happy_win(
    config: E2EConfig,
    api: BotApiProtocol,
    preflight: PreflightResult,
    reply_filter: StageReplyFilter,
    update_offset: int | None,
    before_rowid: int,
) -> dict[str, Any]:
    current_offset = update_offset
    reply_texts: list[str] = []
    sent_ids: list[int] = []
    for spin in range(1, config.max_spins_until_win + 1):
        sent = await api.send_dice(preflight.target_chat_id, "🎰")
        if isinstance(sent.get("message_id"), int):
            sent_ids.append(sent["message_id"])
        await asyncio.sleep(config.rate_limit_seconds)
        replies, current_offset = await poll_stage_replies(
            api=api,
            reply_filter=reply_filter,
            update_offset=current_offset,
            timeout_seconds=config.timeout_seconds,
        )
        reply_texts.extend(_message_text(reply) for reply in replies)
        if latest_event_after(
            config.stage_db_path,
            "happy_moment_win",
            before_rowid,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        ):
            return {
                "name": "spin-until-happy-win",
                "action": "spin_until_happy_win",
                "sent_message_id": sent_ids[-1] if sent_ids else None,
                "reply_count": len(reply_texts),
                "reply_texts": reply_texts,
                "db_validated": True,
                "db_assertion": {"spins": spin},
                "update_offset": current_offset,
            }
    raise SmokeFailureError(f"no happy_moment_win after {config.max_spins_until_win} spins")


async def run_spin_until_heist_loss(
    config: E2EConfig,
    api: BotApiProtocol,
    preflight: PreflightResult,
    reply_filter: StageReplyFilter,
    update_offset: int | None,
    before_rowid: int,
) -> dict[str, Any]:
    current_offset = update_offset
    reply_texts: list[str] = []
    sent_ids: list[int] = []
    for spin in range(1, config.max_spins_until_win + 1):
        sent = await api.send_dice(preflight.target_chat_id, "🎰")
        if isinstance(sent.get("message_id"), int):
            sent_ids.append(sent["message_id"])
        await asyncio.sleep(config.rate_limit_seconds)
        replies, current_offset = await poll_stage_replies(
            api=api,
            reply_filter=reply_filter,
            update_offset=current_offset,
            timeout_seconds=config.timeout_seconds,
        )
        reply_texts.extend(_message_text(reply) for reply in replies)
        contribution = latest_event_after(
            config.stage_db_path,
            "heist_contribution",
            before_rowid,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        loss = latest_event_after(
            config.stage_db_path,
            "loss",
            before_rowid,
            user_id=preflight.tester_bot_id,
            chat_id=preflight.target_chat_id,
        )
        if contribution and loss and _event_metadata(loss).get("during_heist") is True:
            return {
                "name": "spin-until-heist-loss",
                "action": "spin_until_heist_loss",
                "sent_message_id": sent_ids[-1] if sent_ids else None,
                "reply_count": len(reply_texts),
                "reply_texts": reply_texts,
                "db_validated": True,
                "db_assertion": {"spins": spin},
                "update_offset": current_offset,
            }
    raise SmokeFailureError(f"no heist contribution/loss after {config.max_spins_until_win} spins")


def max_event_rowid(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        if not table_exists(conn, "event_history"):
            return 0
        row = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM event_history").fetchone()
    return int(row[0]) if row else 0


def latest_event_after(
    db_path: Path,
    event_type: str,
    after_rowid: int,
    *,
    user_id: int | None = None,
    chat_id: int | None = None,
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    where = ["rowid > ?", "event_type = ?"]
    params: list[Any] = [after_rowid, event_type]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = get_table_columns(conn, "event_history")
        if chat_id is not None and "chat_id" in columns:
            where.append("chat_id = ?")
            params.append(chat_id)
        row = conn.execute(
            f"SELECT rowid, event_id, user_id, event_type, amount, metadata, chat_id FROM event_history WHERE {' AND '.join(where)} ORDER BY rowid DESC LIMIT 1",
            params,
        ).fetchone()
    return dict(row) if row else None


def _event_metadata(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {}
    raw = event.get("metadata")
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise SmokeFailureError(
            f"invalid event metadata JSON for {event.get('event_type')}"
        ) from exc
    if not isinstance(data, dict):
        raise SmokeFailureError(f"event metadata is not an object for {event.get('event_type')}")
    return data


def assert_happy_event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    metadata = _event_metadata(event)
    if metadata.get("happy_moment_multiplier") != 2.0:
        raise SmokeFailureError("happy_moment_win metadata missing multiplier 2.0")
    if metadata.get("happy_moment_name") != "E2E Happy Moment":
        raise SmokeFailureError("happy_moment_win metadata missing E2E Happy Moment name")
    return metadata


def assert_heist_event_metadata(
    contribution: dict[str, Any] | None,
    loss: dict[str, Any] | None,
    win: dict[str, Any] | None,
) -> dict[str, Any]:
    if contribution is None or loss is None or win is None:
        raise SmokeFailureError("missing heist event for metadata assertions")
    contribution_meta = _event_metadata(contribution)
    loss_meta = _event_metadata(loss)
    win_meta = _event_metadata(win)
    if contribution_meta.get("pot_after", 0) < 1:
        raise SmokeFailureError("heist_contribution metadata missing pot_after")
    if loss_meta.get("during_heist") is not True:
        raise SmokeFailureError("loss metadata missing during_heist=true")
    if loss_meta.get("heist_pot_after", 0) < 1:
        raise SmokeFailureError("loss metadata missing heist_pot_after")
    if win_meta.get("total_pot", 0) < 1:
        raise SmokeFailureError("heist_win metadata missing total_pot")
    return {"contribution": contribution_meta, "loss": loss_meta, "win": win_meta}


def _reply_or_metadata_has_happy_marker(reply_texts: list[str], event: dict[str, Any]) -> bool:
    if any("E2E Happy Moment" in text for text in reply_texts):
        return True
    metadata = _event_metadata(event)
    return metadata.get("happy_moment_name") == "E2E Happy Moment"


def _scheduled_metadata_indicates_e2e_hook(metadata: Any) -> bool:
    if metadata is None:
        return False
    raw = str(metadata)
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "e2e_hook" in raw or "E2E Happy Moment" in raw
    if not isinstance(parsed, dict):
        return False
    return parsed.get("source") == "e2e_hook" or parsed.get("name") == "E2E Happy Moment"


def read_schedule_readiness(db_path: Path, *, strict: bool = False) -> dict[str, Any]:
    if not db_path.exists():
        if strict:
            raise SmokeFailureError("schedule-readiness strict mode requires an existing stage DB")
        return {"scheduled_events_present": False, "rows": []}
    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_events'"
        ).fetchone()
        if table is None:
            if strict:
                raise SmokeFailureError("schedule-readiness strict mode requires scheduled_events")
            return {"scheduled_events_present": False, "rows": []}
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT event_id, event_type, chat_id, scheduled_at, timezone, source_date, status, metadata
            FROM scheduled_events
            WHERE event_type IN ('happy_moment_start', 'happy_moment_end', 'heist_warning', 'heist_start', 'heist_end')
            ORDER BY scheduled_at DESC
            LIMIT 20
            """
        ).fetchall()
        stale_e2e_running_rows = conn.execute(
            """
            SELECT event_id, event_type, chat_id, scheduled_at, timezone, source_date, status, metadata
            FROM scheduled_events
            WHERE status = 'running'
            ORDER BY scheduled_at DESC
            """
        ).fetchall()
    result = {"scheduled_events_present": True, "rows": [dict(row) for row in rows]}
    if strict:
        stale_e2e_running = [
            dict(row)
            for row in stale_e2e_running_rows
            if _scheduled_metadata_indicates_e2e_hook(row["metadata"])
        ]
        if stale_e2e_running:
            event_ids = ", ".join(str(row["event_id"]) for row in stale_e2e_running)
            raise SmokeFailureError(
                "schedule-readiness strict mode found stale E2E running scheduled_events: "
                f"{event_ids}"
            )
        present_types = {str(row["event_type"]) for row in result["rows"]}
        required_types = {"happy_moment_start", "heist_start"}
        missing = sorted(required_types.difference(present_types))
        if missing:
            raise SmokeFailureError(
                f"schedule-readiness strict mode missing event types: {', '.join(missing)}"
            )
        result["strict"] = True
        result["required_event_types"] = sorted(required_types)
    return result


async def validate_stage_command_menu(stage_api: BotApiProtocol | None) -> dict[str, Any]:
    if stage_api is None:
        return {"skipped": f"{ENV_STAGE_BOT_TOKEN} not set"}
    scopes = {
        "default": {"type": "default"},
        "all_private_chats": {"type": "all_private_chats"},
        "all_group_chats": {"type": "all_group_chats"},
    }
    required = {"balance", "bid", "safe", "stats", "top", "dice", "take", "give", "credit", "help"}
    forbidden = {"start", "spin", "stop"}
    by_scope: dict[str, list[str]] = {}
    for scope_name, scope in scopes.items():
        commands = await stage_api.get_my_commands(scope=scope)
        names = [str(command.get("command", "")) for command in commands]
        by_scope[scope_name] = names
        stale = sorted(forbidden.intersection(names))
        if stale:
            raise SmokeFailureError(
                f"stage command menu advertises stale commands in {scope_name}: {', '.join(stale)}"
            )
    group_scope = {"type": "all_group_chats"}
    names = by_scope["all_group_chats"]
    missing = sorted(required.difference(names))
    if missing:
        raise SmokeFailureError(f"stage command menu missing commands: {', '.join(missing)}")
    return {"commands": names, "missing": [], "scope": group_scope, "scopes": by_scope}


async def execute(
    config: E2EConfig, api: BotApiProtocol, stage_api: BotApiProtocol | None = None
) -> SmokeReport:
    report = SmokeReport(ok=False, config=config.redacted())
    preflight = await run_preflight(config, api)
    report.preflight = asdict(preflight)
    report.command_menu = await validate_stage_command_menu(stage_api)
    if config.scenario == "schedule-readiness":
        report.schedule_readiness = read_schedule_readiness(
            config.stage_db_path, strict=config.schedule_strict
        )
        report.db_assertions = {"skipped": "schedule-readiness is read-only"}
        report.ok = True
        return report
    if config.scenario in {"events", "event-flows"}:
        report.steps, report.db_assertions = await run_event_flows(config, api, preflight)
        report.ok = True
        return report
    before = snapshot_user_state(config.stage_db_path, preflight.tester_bot_id)
    report.steps = await run_scenario(config, api, preflight)
    if config.dry_run:
        report.db_assertions = {"skipped": "dry-run sends no scenario messages"}
    elif config.scenario == "stage-parity":
        report.db_assertions = stage_parity_db_assertions(
            config.stage_db_path, preflight.tester_bot_id, before=before
        )
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


def _optional_secret(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
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
    parser = argparse.ArgumentParser(description="Run TASK-019/TASK-021 staging Telegram E2E smoke")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=f"Override {ENV_DRY_RUN}=true; preflight only, no scenario messages",
    )
    parser.add_argument(
        "--scenario",
        choices=["smoke", "stage-parity", "economy", "schedule-readiness", "events", "event-flows"],
        help=f"Override {ENV_SCENARIO}",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str]) -> int:
    args = parse_args(argv)
    env = dict(os.environ)
    if args.dry_run:
        env[ENV_DRY_RUN] = "true"
    if args.scenario:
        env[ENV_SCENARIO] = args.scenario
    try:
        config = E2EConfig.from_env(env)
        stage_api = TelegramBotApi(config.stage_bot_token) if config.stage_bot_token else None
        report = await execute(config, TelegramBotApi(config.tester_token), stage_api)
    except (ConfigError, SmokeFailureError) as exc:
        safe_config: dict[str, Any] = {"error": "configuration not loaded"}
        try:
            safe_config = E2EConfig.from_env(env).redacted()
        except ConfigError:
            pass
        report = SmokeReport(ok=False, config=safe_config, errors=[str(exc)])
        print(report.to_json())
        return 2
    except sqlite3.Error as exc:
        safe_config = {"error": "configuration not loaded"}
        try:
            safe_config = E2EConfig.from_env(env).redacted()
        except ConfigError:
            pass
        report = SmokeReport(
            ok=False,
            config=safe_config,
            errors=[f"stage DB schema/query error: {exc}"],
        )
        print(report.to_json())
        return 2
    print(report.to_json())
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
