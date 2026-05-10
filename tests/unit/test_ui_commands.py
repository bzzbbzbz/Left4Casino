"""Unit tests for Bot API command menu contract."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

from bot.ui_commands import set_bot_commands

pytestmark = pytest.mark.unit


class FakeLocalization:
    def format_value(self, key: str, args: dict[str, Any] | None = None) -> str:  # noqa: ARG002
        return key


class FakeBot:
    def __init__(self) -> None:
        self.deleted_scopes: list[Any] = []
        self.set_calls: list[dict[str, Any]] = []

    async def delete_my_commands(self, *, scope: Any) -> None:
        self.deleted_scopes.append(scope)

    async def set_my_commands(self, *, commands: list[Any], scope: Any) -> None:
        self.set_calls.append({"commands": commands, "scope": scope})


@pytest.mark.asyncio
async def test_set_bot_commands_uses_group_contract_and_clears_stale_scopes() -> None:
    bot = FakeBot()

    await set_bot_commands(bot, FakeLocalization())  # type: ignore[arg-type]

    assert [type(scope) for scope in bot.deleted_scopes] == [
        BotCommandScopeDefault,
        BotCommandScopeAllPrivateChats,
    ]
    assert len(bot.set_calls) == 1
    assert isinstance(bot.set_calls[0]["scope"], BotCommandScopeAllGroupChats)

    command_names = [command.command for command in bot.set_calls[0]["commands"]]
    assert command_names == [
        "balance",
        "bid",
        "safe",
        "stats",
        "top",
        "dice",
        "take",
        "give",
        "credit",
        "help",
    ]
    assert not {"start", "spin", "stop"}.intersection(command_names)
