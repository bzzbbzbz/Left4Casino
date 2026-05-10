"""Unit tests for TASK-019 Telegram E2E smoke runner."""

from __future__ import annotations

import importlib.util
import json
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

    async def get_my_commands(self, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return []

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


class FakeReplyEconomyBot(FakeNoReplyBot):
    def __init__(self, db_path: Path, user_id: int = 42) -> None:
        super().__init__(db_path, user_id)
        self.update_id = 0
        self.replies: list[dict[str, Any]] = []
        self.sent_count = 0

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        self.sent_count += 1
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                if text.startswith("/bid"):
                    row = conn.execute(
                        "SELECT balance FROM users WHERE user_id = ?", (self.user_id,)
                    ).fetchone()
                    balance = row[0] if row else "0"
                    conn.execute(
                        "UPDATE users SET bid = ? WHERE user_id = ?", (balance, self.user_id)
                    )
                elif text.startswith("/safe") and " -1" not in text:
                    conn.execute(
                        "UPDATE users SET balance = '49', safe_balance = '1' WHERE user_id = ?",
                        (self.user_id,),
                    )
                elif text.startswith("/safe") and " -1" in text:
                    conn.execute(
                        "UPDATE users SET balance = '50', safe_balance = '0' WHERE user_id = ?",
                        (self.user_id,),
                    )
                elif text.startswith("/credit"):
                    conn.execute(
                        "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
                        ("s1", self.user_id, "active"),
                    )
        self._queue_reply(chat_id, "ok")
        return {"message_id": self.sent_count, "chat": {"id": chat_id}, "text": text}

    async def send_dice(self, chat_id: int, emoji: str) -> dict[str, Any]:
        self.sent_count += 1
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT balance FROM users WHERE user_id = ?", (self.user_id,)
                ).fetchone()
                balance = row[0] if row else "0"
                if balance == "1":
                    conn.execute(
                        "UPDATE users SET balance = '0', bankruptcy_count = bankruptcy_count + 1 "
                        "WHERE user_id = ?",
                        (self.user_id,),
                    )
                    conn.execute(
                        "INSERT INTO event_history (user_id, event_type) VALUES (?,?)",
                        (self.user_id, "bankruptcy"),
                    )
                elif self.sent_count >= 2:
                    conn.execute(
                        "UPDATE users SET balance = '57' WHERE user_id = ?", (self.user_id,)
                    )
                    conn.execute(
                        "INSERT INTO event_history (user_id, event_type) VALUES (?,?)",
                        (self.user_id, "win"),
                    )
                else:
                    conn.execute(
                        "INSERT INTO event_history (user_id, event_type) VALUES (?,?)",
                        (self.user_id, "loss"),
                    )
        self._queue_reply(chat_id, "spin")
        return {
            "message_id": self.sent_count,
            "chat": {"id": chat_id},
            "dice": {"emoji": emoji, "value": 64},
        }

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0, allowed_updates: list[str] | None = None
    ) -> list[dict[str, Any]]:
        updates = self.replies
        self.replies = []
        return updates

    def _queue_reply(self, chat_id: int, text: str) -> None:
        self.update_id += 1
        self.replies.append(
            {
                "update_id": self.update_id,
                "message": {
                    "message_id": self.update_id,
                    "chat": {"id": chat_id},
                    "from": {"id": 777, "username": "Left4CasinoStageBot"},
                    "text": text,
                },
            }
        )


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
            "(user_id INTEGER PRIMARY KEY, balance TEXT, safe_balance TEXT, bid TEXT, "
            "state TEXT DEFAULT 'IDLE', bankruptcy_count INTEGER DEFAULT 0)"
        )
        conn.execute("CREATE TABLE event_history (user_id INTEGER, event_type TEXT)")
        conn.execute(
            "CREATE TABLE ai_credit_sessions "
            "(session_id TEXT, user_id INTEGER, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
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
    update_filter = smoke.StageReplyFilter(
        stage_bot_username="StageBot", stage_bot_id=42, target_chat_id=-1001
    )
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
        {
            "update_id": 3,
            "message": {
                "message_id": 12,
                "chat": {"id": -2002},
                "from": {"id": 42, "username": "StageBot"},
                "text": "cross-chat noise",
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


def test_smoke_db_assertion_still_requires_state_delta(tmp_path: Path) -> None:
    db_path = tmp_path / "casino.db"
    create_user_db(db_path)
    before = smoke.snapshot_user_state(db_path, 42)

    with pytest.raises(smoke.SmokeFailureError, match="did not record balance/event changes"):
        smoke.assert_stage_db_state(db_path, 42, before=before)


@pytest.mark.asyncio
async def test_stage_parity_execute_does_not_require_db_state_delta(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_DRY_RUN"] = "false"
    env["TELEGRAM_E2E_SCENARIO"] = "stage-parity"
    env["TELEGRAM_E2E_RATE_LIMIT_SECONDS"] = "0"
    env["TELEGRAM_E2E_TIMEOUT_SECONDS"] = "0.01"
    config = smoke.E2EConfig.from_env(env)

    report = await smoke.execute(config, FakeReplyEconomyBot(db_path), stage_api=None)

    assert report.ok is True
    assert [step["name"] for step in report.steps] == ["start-no-legacy", "balance"]
    assert report.db_assertions is not None
    assert report.db_assertions["skipped"].startswith("stage-parity validates")
    assert report.db_assertions["before"] == report.db_assertions["after"]


def test_credit_assertion_requires_fresh_session(tmp_path: Path) -> None:
    db_path = tmp_path / "casino.db"
    create_user_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
            ("stale", 42, "active"),
        )
    before = smoke.snapshot_credit_sessions(db_path, 42)

    with pytest.raises(smoke.SmokeFailureError, match="fresh active"):
        smoke.assert_credit_session_started(db_path, 42, before=before)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
            ("fresh", 42, "active"),
        )

    result = smoke.assert_credit_session_started(db_path, 42, before=before)
    assert result["after"]["latest_session_id"] == "fresh"


def test_credit_assertion_supports_sessions_without_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "casino.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE ai_credit_sessions (session_id TEXT, user_id INTEGER, status TEXT)"
        )
        conn.execute(
            "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
            ("stale", 42, "active"),
        )
    before = smoke.snapshot_credit_sessions(db_path, 42)

    with pytest.raises(smoke.SmokeFailureError, match="fresh active"):
        smoke.assert_credit_session_started(db_path, 42, before=before)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
            ("fresh", 42, "active"),
        )

    result = smoke.assert_credit_session_started(db_path, 42, before=before)
    assert result["after"]["latest_session_id"] == "fresh"
    assert result["after"]["latest_status"] == "active"
    assert result["after"]["schema"]["order_columns"] == ["rowid"]


@pytest.mark.asyncio
async def test_async_main_reports_sqlite_schema_errors_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_DRY_RUN"] = "false"
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    async def raise_schema_error(
        config: smoke.E2EConfig,
        api: smoke.BotApiProtocol,
        stage_api: smoke.BotApiProtocol | None = None,
    ) -> smoke.SmokeReport:
        raise sqlite3.OperationalError("no such column: created_at")

    monkeypatch.setattr(smoke, "execute", raise_schema_error)

    exit_code = await smoke.async_main([])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == ["stage DB schema/query error: no such column: created_at"]


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


def test_stage_token_is_optional_and_redacted(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_STAGE_BOT_TOKEN"] = "stage-secret"

    config = smoke.E2EConfig.from_env(env)

    assert config.stage_bot_token == "stage-secret"
    assert config.redacted()["stage_bot_token"] == "<redacted>"


def test_legacy_start_detection_rejects_text_and_reply_markup() -> None:
    with pytest.raises(smoke.SmokeFailureError, match="legacy casino welcome"):
        smoke.assert_no_legacy_start_reply([{"text": "Добро пожаловать в казино!"}])
    with pytest.raises(smoke.SmokeFailureError, match="legacy casino welcome"):
        smoke.assert_no_legacy_start_reply([{"text": "Показать клавиатуру — /spin"}])

    with pytest.raises(smoke.SmokeFailureError, match="reply keyboard"):
        smoke.assert_no_legacy_start_reply([{"text": "ok", "reply_markup": {"keyboard": []}}])

    smoke.assert_no_legacy_start_reply([])


@pytest.mark.asyncio
async def test_command_menu_validation_uses_optional_stage_token_api() -> None:
    class FakeStageApi(FakeNoReplyBot):
        def __init__(self) -> None:
            super().__init__()
            self.scope: dict[str, Any] | None = None

        async def get_my_commands(
            self, scope: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            self.scope = scope
            return [
                {"command": "balance"},
                {"command": "bid"},
                {"command": "safe"},
                {"command": "stats"},
                {"command": "top"},
                {"command": "dice"},
                {"command": "take"},
                {"command": "give"},
                {"command": "credit"},
                {"command": "help"},
            ]

    api = FakeStageApi()
    result = await smoke.validate_stage_command_menu(api)

    assert result["missing"] == []
    assert result["scope"] == {"type": "all_group_chats"}
    assert api.scope == {"type": "all_group_chats"}
    assert await smoke.validate_stage_command_menu(None) == {
        "skipped": "TELEGRAM_E2E_STAGE_BOT_TOKEN not set"
    }


@pytest.mark.asyncio
async def test_command_menu_validation_rejects_stale_advertised_commands() -> None:
    class FakeStageApi(FakeNoReplyBot):
        async def get_my_commands(
            self, scope: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            return [
                {"command": "balance"},
                {"command": "bid"},
                {"command": "safe"},
                {"command": "stats"},
                {"command": "top"},
                {"command": "dice"},
                {"command": "take"},
                {"command": "give"},
                {"command": "credit"},
                {"command": "help"},
                {"command": "spin"},
            ]

    with pytest.raises(smoke.SmokeFailureError, match="stale commands: spin"):
        await smoke.validate_stage_command_menu(FakeStageApi())


def test_db_mutation_guard_requires_explicit_env(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    config = make_config(tmp_path, settings_path, db_path)

    with pytest.raises(smoke.ConfigError, match="ALLOW_DB_MUTATION"):
        smoke.set_tester_balance_for_stage(config, 42, 0)

    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_ALLOW_DB_MUTATION"] = "1"
    config = smoke.E2EConfig.from_env(env)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE users SET safe_balance = '7', bid = '9', state = 'IN_DIALOGUE'")
        conn.execute(
            "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?,?,?)",
            ("old-active", 42, "active"),
        )
    smoke.set_tester_balance_for_stage(config, 42, 0)

    state = smoke.snapshot_user_state(db_path, 42)
    assert state["balance"] == 0  # type: ignore[index]
    assert state["safe_balance"] == 0  # type: ignore[index]
    assert state["bid"] == 1  # type: ignore[index]
    with sqlite3.connect(db_path) as conn:
        user_state = conn.execute("SELECT state FROM users WHERE user_id = 42").fetchone()[0]
        credit_status = conn.execute(
            "SELECT status FROM ai_credit_sessions WHERE session_id = 'old-active'"
        ).fetchone()[0]
    assert user_state == "IDLE"
    assert credit_status == "terminated"


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
            "db_assertion": None,
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


@pytest.mark.asyncio
async def test_economy_safe_deposit_withdraw_steps_with_db_guard(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_DRY_RUN"] = "false"
    env["TELEGRAM_E2E_ALLOW_DB_MUTATION"] = "1"
    env["TELEGRAM_E2E_SCENARIO"] = "economy"
    env["TELEGRAM_E2E_RATE_LIMIT_SECONDS"] = "0"
    env["TELEGRAM_E2E_TIMEOUT_SECONDS"] = "0.01"
    env["TELEGRAM_E2E_MAX_SPINS_UNTIL_WIN"] = "1"
    config = smoke.E2EConfig.from_env(env)
    preflight = smoke.PreflightResult(
        -1001, 42, "TesterBot", 777, "Left4CasinoStageBot", "Stage chat"
    )

    results = await smoke.run_scenario(config, FakeReplyEconomyBot(db_path), preflight)

    by_name = {result["name"]: result for result in results}
    assert by_name["bid-all-in"]["db_assertion"] == {"bid": 50, "balance": 50}
    assert by_name["safe-deposit"]["db_assertion"]["safe_balance"] == 1
    assert by_name["safe-withdraw"]["db_assertion"]["safe_balance"] == 0
    assert by_name["credit-entry"]["db_assertion"]["after"]["latest_status"] == "active"
    assert by_name["spin-until-bankruptcy"]["db_assertion"]["after_bankruptcy_events"] == 1


@pytest.mark.asyncio
async def test_spin_until_win_loop_stops_on_first_win(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.stage.toml"
    db_path = tmp_path / "casino.db"
    write_stage_settings(settings_path, [-1001])
    create_user_db(db_path)
    env = base_env(tmp_path, settings_path, db_path)
    env["TELEGRAM_E2E_DRY_RUN"] = "false"
    env["TELEGRAM_E2E_RATE_LIMIT_SECONDS"] = "0"
    env["TELEGRAM_E2E_TIMEOUT_SECONDS"] = "0.01"
    env["TELEGRAM_E2E_MAX_SPINS_UNTIL_WIN"] = "3"
    config = smoke.E2EConfig.from_env(env)
    preflight = smoke.PreflightResult(
        -1001, 42, "TesterBot", 777, "Left4CasinoStageBot", "Stage chat"
    )

    result = await smoke.run_spin_until_win(
        config,
        FakeReplyEconomyBot(db_path),
        preflight,
        smoke.StageReplyFilter(stage_bot_username="Left4CasinoStageBot", stage_bot_id=777),
        None,
    )

    assert result["db_validated"] is True
    assert result["db_assertion"]["spins"] == 2


def test_schedule_readiness_reports_rows_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "casino.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE scheduled_events "
            "(event_id TEXT, event_type TEXT, chat_id INTEGER, scheduled_at TEXT, timezone TEXT, "
            "source_date TEXT, status TEXT, metadata TEXT)"
        )
        conn.execute(
            "INSERT INTO scheduled_events VALUES (?,?,?,?,?,?,?,?)",
            (
                "e1",
                "happy_moment_start",
                -1001,
                "2026-05-10T10:00:00",
                "UTC",
                "2026-05-10",
                "scheduled",
                "{}",
            ),
        )

    report = smoke.read_schedule_readiness(db_path)

    assert report["scheduled_events_present"] is True
    assert report["rows"][0]["event_type"] == "happy_moment_start"

    with pytest.raises(smoke.SmokeFailureError, match="missing event types"):
        smoke.read_schedule_readiness(db_path, strict=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO scheduled_events VALUES (?,?,?,?,?,?,?,?)",
            (
                "e2",
                "heist_start",
                -1001,
                "2026-05-10T11:00:00",
                "UTC",
                "2026-05-10",
                "scheduled",
                "{}",
            ),
        )
    strict_report = smoke.read_schedule_readiness(db_path, strict=True)
    assert strict_report["strict"] is True
