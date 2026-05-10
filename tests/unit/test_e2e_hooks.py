"""Unit tests for TASK-021 staging-only E2E hook guards."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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
    assert e2e_hooks.e2e_hooks_enabled({"LEFT4CASINO_E2E_HOOKS_ENABLED": "1"}) is True
    assert e2e_hooks.e2e_hooks_enabled({"LEFT4CASINO_E2E_HOOKS_ENABLED": "true"}) is True


@pytest.mark.asyncio
async def test_e2e_hook_caller_guard_allows_unset_or_matching_user() -> None:
    message = FakeMessage(user_id=42)

    assert await e2e_hooks._caller_allowed(message, {}) is True  # type: ignore[attr-defined]
    assert (
        await e2e_hooks._caller_allowed(  # type: ignore[attr-defined]
            message, {"LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "42"}
        )
        is True
    )
    assert message.answers == []


@pytest.mark.asyncio
async def test_e2e_hook_caller_guard_rejects_mismatch() -> None:
    message = FakeMessage(user_id=7)

    allowed = await e2e_hooks._caller_allowed(  # type: ignore[attr-defined]
        message, {"LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID": "42"}
    )

    assert allowed is False
    assert message.answers == ["E2E hooks forbidden for this user"]
