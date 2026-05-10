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
