"""Unit tests for TASK-021 staging-only E2E hook guards."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytz

from bot.handlers import e2e_hooks

pytestmark = pytest.mark.unit


class FakeMessage:
    def __init__(self, user_id: int | None = 42) -> None:
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.chat = SimpleNamespace(id=-1001)
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:  # noqa: ANN003
        self.answers.append(text)


def test_e2e_hooks_disabled_by_default_and_enabled_by_env() -> None:
    assert e2e_hooks.e2e_hooks_enabled({}) is False
    assert e2e_hooks.e2e_hooks_enabled({"LEFT4CASINO_E2E_HOOKS_ENABLED": "0"}) is False
    assert e2e_hooks.e2e_hooks_enabled({"LEFT4CASINO_E2E_HOOKS_ENABLED": "1"}) is False
    assert (
        e2e_hooks.e2e_hooks_enabled(
            {
                "LEFT4CASINO_E2E_HOOKS_ENABLED": "true",
                "LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "42",
            }
        )
        is True
    )
    assert (
        e2e_hooks.e2e_hooks_enabled(
            {
                "LEFT4CASINO_E2E_HOOKS_ENABLED": "1",
                "LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "not-int",
            }
        )
        is False
    )


@pytest.mark.asyncio
async def test_e2e_hook_caller_guard_requires_matching_user() -> None:
    message = FakeMessage(user_id=42)

    assert await e2e_hooks._caller_allowed(message, {}) is False  # type: ignore[attr-defined]
    assert (
        await e2e_hooks._caller_allowed(  # type: ignore[attr-defined]
            message, {"LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "42"}
        )
        is True
    )
    assert message.answers == ["E2E hooks forbidden: missing or invalid allowed user guard"]


@pytest.mark.asyncio
async def test_e2e_hook_caller_guard_rejects_mismatch() -> None:
    message = FakeMessage(user_id=7)

    allowed = await e2e_hooks._caller_allowed(  # type: ignore[attr-defined]
        message, {"LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "42"}
    )

    assert allowed is False
    assert message.answers == ["E2E hooks forbidden for this user"]


class FakeDb:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.events: list[tuple] = []

    async def upsert_scheduled_event(self, **kwargs) -> None:  # noqa: ANN003
        self.upserts.append(kwargs)

    async def add_event(self, *args) -> None:  # noqa: ANN002
        self.events.append(args)


class FakeHappyService:
    def __init__(self, active_name: str | None = None, *, e2e_owned: bool = False) -> None:
        self.timezone = pytz.UTC
        self.active_moment = None
        self.started = 0
        self.ended = 0
        if active_name is not None:
            self.active_moment = SimpleNamespace(name=active_name, e2e_owned=e2e_owned)

    async def start_moment(self, moment) -> None:  # noqa: ANN001
        self.started += 1
        self.active_moment = SimpleNamespace(name=moment.name)

    async def end_moment(self) -> None:
        self.ended += 1
        self.active_moment = None


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class FakeHeistService:
    def __init__(self, state=None) -> None:  # noqa: ANN001
        self.timezone = pytz.UTC
        self.active_heists = {-1001: state} if state is not None else {}
        self.bot = FakeBot()
        self.ended: list[int] = []

    def is_active(self, chat_id: int) -> bool:
        return chat_id in self.active_heists

    def get_heist_state(self, chat_id: int):  # noqa: ANN201
        return self.active_heists.get(chat_id)

    async def end_heist(self, chat_id: int) -> None:
        self.ended.append(chat_id)
        self.active_heists.pop(chat_id, None)


@pytest.mark.asyncio
async def test_happy_start_refuses_non_e2e_active_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID", "42")
    message = FakeMessage(user_id=42)
    service = FakeHappyService(active_name="Real Happy Moment")
    db = FakeDb()

    await e2e_hooks.cmd_e2e_happy_start(message, service, db)  # type: ignore[arg-type]

    assert message.answers == ["E2E Happy Moment refused: non-E2E Happy Moment is active"]
    assert service.started == 0
    assert service.ended == 0
    assert db.upserts == []


@pytest.mark.asyncio
async def test_happy_start_can_restart_e2e_owned_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID", "42")
    message = FakeMessage(user_id=42)
    service = FakeHappyService(active_name="E2E Happy Moment", e2e_owned=True)
    db = FakeDb()

    await e2e_hooks.cmd_e2e_happy_start(message, service, db)  # type: ignore[arg-type]

    assert service.ended == 1
    assert service.started == 1
    assert service.active_moment.e2e_owned is True
    assert message.answers[-1].startswith("E2E Happy Moment started")


@pytest.mark.asyncio
async def test_heist_start_refuses_non_e2e_active_without_payout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID", "42")
    message = FakeMessage(user_id=42)
    service = FakeHeistService(state=SimpleNamespace(e2e_owned=False))
    db = FakeDb()

    await e2e_hooks.cmd_e2e_heist_start(message, service, db)  # type: ignore[arg-type]

    assert message.answers == ["E2E Heist refused: non-E2E Heist is active in this chat"]
    assert service.ended == []
    assert db.events == []


@pytest.mark.asyncio
async def test_heist_start_deletes_only_e2e_owned_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID", "42")
    message = FakeMessage(user_id=42)
    service = FakeHeistService(state=SimpleNamespace(e2e_owned=True))
    db = FakeDb()

    await e2e_hooks.cmd_e2e_heist_start(message, service, db)  # type: ignore[arg-type]

    assert service.ended == []
    assert service.active_heists[-1001].e2e_owned is True
    assert db.events[0][2] == "heist_start"
