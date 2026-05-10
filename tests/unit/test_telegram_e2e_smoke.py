"""Unit tests for TASK-019 Telegram E2E smoke runner."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def load_smoke_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "telegram_e2e_smoke.py"
    spec = importlib.util.spec_from_file_location("telegram_e2e_smoke", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_e2e_smoke"] = module
    spec.loader.exec_module(module)
    return module


smoke = load_smoke_module()


class FakeNoReplyBot:
    def __init__(self, db_path: Path | None = None, user_id: int = 42) -> None:
        self.db_path = db_path
        self.user_id = user_id

    async def get_me(self) -> dict[str, Any]:
        return {"id": self.user_id, "username": "TesterBot"}

    async def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        if isinstance(chat_id, str):
            return {"id": 777, "username": chat_id.removeprefix("@")}
        return {"id": chat_id, "title": "Stage chat"}

    async def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        return {"status": "member", "user": {"id": user_id}}

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        return {"message_id": 10, "chat": {"id": chat_id}, "text": text}

    async def send_dice(self, chat_id: int, emoji: str) -> dict[str, Any]:
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE users SET balance = ? WHERE user_id = ?", ("49", self.user_id))
                conn.execute(
                    "INSERT INTO event_history (user_id, event_type) VALUES (?,?)",
                    (self.user_id, "loss"),
                )
        return {"message_id": 11, "chat": {"id": chat_id}, "dice": {"emoji": emoji, "value": 1}}

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0, allowed_updates: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return []


def write_stage_settings(path: Path, allowed_chat_ids: list[int]) -> None:
    ids = ", ".join(str(chat_id) for chat_id in allowed_chat_ids)
    path.write_text(
        "[bot]\n"
        'token = "must-not-be-read"\n'
        "[chat_restrictions]\n"
        "block_private_chats = true\n"
        f"allowed_chat_ids = [{ids}]\n",
        encoding="utf-8",
    )


def base_env(tmp_path: Path, settings_path: Path, db_path: Path) -> dict[str, str]:
    return {
        "TELEGRAM_E2E_TESTER_TOKEN": "fake-token-for-unit-tests",
        "TELEGRAM_E2E_STAGE_BOT_USERNAME": "@Left4CasinoStageBot",
        "TELEGRAM_E2E_STAGE_SETTINGS_PATH": str(settings_path),
        "TELEGRAM_E2E_STAGE_DB_PATH": str(db_path),
        "TELEGRAM_E2E_TARGET_CHAT_ID": "-1001",
        "TELEGRAM_E2E_DRY_RUN": "true",
        "TELEGRAM_E2E_ALLOWED_DB_PREFIX": str(tmp_path),
    }


def make_config(tmp_path: Path, settings_path: Path, db_path: Path, *, dry_run: bool = False):
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_DRY_RUN"] = "true" if dry_run else "false"
    env["TELEGRAM_E2E_TIMEOUT_SECONDS"] = "0.01"
    env["TELEGRAM_E2E_RATE_LIMIT_SECONDS"] = "0"
    return smoke.E2EConfig.from_env(env)


def create_user_db(db_path: Path, user_id: int = 42) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE users "
            "(user_id INTEGER PRIMARY KEY, balance TEXT, safe_balance TEXT, bid TEXT)"
        )
        conn.execute("CREATE TABLE event_history (user_id INTEGER, event_type TEXT)")
        conn.execute(
            "INSERT INTO users (user_id, balance, safe_balance, bid) VALUES (?,?,?,?)",
            (user_id, "50", "0", "1"),
        )


def test_env_parsing_normalizes_username_and_redacts_token(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "bot" / "casino.db"
    env = base_env(tmp_path, settings_path, db_path)

    config = smoke.E2EConfig.from_env(env)

    assert config.stage_bot_username == "Left4CasinoStageBot"
    assert config.target_chat_id == -1001
    assert config.dry_run is True
    assert config.redacted()["tester_token"] == "<redacted>"


def test_safety_rejects_db_path_outside_allowed_stage_prefix(tmp_path: Path) -> None:
    db_path = tmp_path / "prod" / "casino.db"

    with pytest.raises(smoke.ConfigError, match="prod"):
        smoke.validate_stage_db_path(db_path, tmp_path)

    with pytest.raises(smoke.ConfigError, match="default/prod database path"):
        smoke.validate_stage_db_path(
            Path("/root/n8n-install/python-runner/bot/casino.db"), tmp_path
        )


def test_safety_allows_stage_db_filename_under_allowed_prefix(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "casino.stage.db"

    assert smoke.validate_stage_db_path(db_path, tmp_path) == db_path.resolve(strict=False)


def test_safety_rejects_prod_component_and_non_db_suffix(tmp_path: Path) -> None:
    with pytest.raises(smoke.ConfigError, match="prod component"):
        smoke.validate_stage_db_path(
            tmp_path / "python-runner-prod" / "data" / "casino.stage.db", tmp_path
        )

    with pytest.raises(smoke.ConfigError, match=r"\.db"):
        smoke.validate_stage_db_path(tmp_path / "data" / "casino.stage.sqlite", tmp_path)


def test_target_chat_required_when_multiple_allowed_ids(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001, -1002])
    env = base_env(tmp_path, settings_path, db_path)
    env.pop("TELEGRAM_E2E_TARGET_CHAT_ID")
    config = smoke.E2EConfig.from_env(env)
    settings = smoke.parse_safe_stage_settings(settings_path)

    with pytest.raises(smoke.ConfigError, match="multiple allowed_chat_ids"):
        smoke.resolve_target_chat_id(config, settings)


def test_update_filter_accepts_only_stage_bot_and_dedupes() -> None:
    update_filter = smoke.StageReplyFilter(stage_bot_username="StageBot", stage_bot_id=42)
    updates: list[dict[str, Any]] = [
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": -1001},
                "from": {"id": 42, "username": "StageBot"},
                "text": "Баланс",
            },
        },
        {
            "update_id": 2,
            "message": {
                "message_id": 11,
                "chat": {"id": -1001},
                "from": {"id": 77, "username": "OtherBot"},
                "text": "noise",
            },
        },
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": -1001},
                "from": {"id": 42, "username": "StageBot"},
                "text": "duplicate",
            },
        },
    ]

    accepted = update_filter.filter_new(updates)
    assert [message["text"] for message in accepted] == ["Баланс"]
    assert update_filter.filter_new(updates) == []


def test_db_assertions_decode_text_money(tmp_path: Path) -> None:
    db_path = tmp_path / "casino.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE users "
            "(user_id INTEGER PRIMARY KEY, balance TEXT, safe_balance TEXT, bid TEXT)"
        )
        conn.execute("CREATE TABLE event_history (user_id INTEGER, event_type TEXT)")
        conn.execute(
            "INSERT INTO users (user_id, balance, safe_balance, bid) VALUES (?,?,?,?)",
            (42, str(10**24), "250", "1"),
        )
        conn.execute("INSERT INTO event_history (user_id, event_type) VALUES (?,?)", (42, "win"))

    result = smoke.assert_stage_db_state(db_path, 42)

    assert result["after"]["balance"] == 10**24
    assert result["after"]["safe_balance"] == 250
    assert result["after"]["event_count"] == 1


def test_report_does_not_include_token(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    token = "fake-secret-token-value"
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_TESTER_TOKEN"] = token
    config = smoke.E2EConfig.from_env(env)
    report = smoke.SmokeReport(ok=True, config=config.redacted())

    serialized = report.to_json()

    assert token not in serialized
    assert "<redacted>" in serialized


@pytest.mark.asyncio
async def test_dice_step_uses_db_fallback_when_reply_is_not_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    config = make_config(tmp_path, settings_path, db_path)
    preflight = smoke.PreflightResult(
        target_chat_id=-1001,
        tester_bot_id=42,
        tester_username="TesterBot",
        stage_bot_id=777,
        stage_bot_username="Left4CasinoStageBot",
        chat_title="Stage chat",
    )
    monkeypatch.setattr(
        smoke,
        "build_smoke_steps",
        lambda _username: [smoke.ScenarioStep("slots", "dice", emoji="🎰")],
    )

    results = await smoke.run_scenario(config, FakeNoReplyBot(db_path), preflight)

    assert results == [
        {
            "name": "slots",
            "action": "dice",
            "sent_message_id": 11,
            "reply_count": 0,
            "reply_texts": [],
            "db_validated": True,
        }
    ]


@pytest.mark.asyncio
async def test_message_step_still_requires_visible_reply_even_if_db_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    config = make_config(tmp_path, settings_path, db_path)
    preflight = smoke.PreflightResult(
        target_chat_id=-1001,
        tester_bot_id=42,
        tester_username="TesterBot",
        stage_bot_id=777,
        stage_bot_username="Left4CasinoStageBot",
        chat_title="Stage chat",
    )
    monkeypatch.setattr(
        smoke,
        "build_smoke_steps",
        lambda _username: [
            smoke.ScenarioStep("balance", "message", "/balance@Left4CasinoStageBot")
        ],
    )

    with pytest.raises(smoke.SmokeFailureError, match="timeout waiting for stage bot reply"):
        await smoke.run_scenario(config, FakeNoReplyBot(db_path), preflight)
