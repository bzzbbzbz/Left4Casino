"""Integration tests for /stats and /top commands."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.group_games import cmd_stats, cmd_top


def _message(user_id: int, username: str, text: str, chat_type: str = "group") -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.from_user.first_name = username
    message.chat.id = -1001234567890
    message.chat.type = chat_type
    message.chat.title = "Test Group"
    message.text = text
    message.reply = AsyncMock()
    return message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stats_shows_individual_user_stats(test_db) -> None:
    await test_db.register_user(701, "alice")
    await test_db.set_balance(701, 123)
    await test_db.update_user_group(701, -1001234567890)
    await test_db.add_event(str(uuid.uuid4()), 701, "win", 30, chat_id=-1001234567890)

    message = _message(701, "alice", "/stats")
    await cmd_stats(message, test_db)

    text = message.reply.call_args[0][0]
    assert "Статистика игрока" in text
    assert "Баланс: 123" in text
    assert "Позиция в рейтинге" in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stats_rejects_unknown_username(test_db) -> None:
    await test_db.register_user(701, "alice")
    await test_db.update_user_group(701, -1001234567890)

    message = _message(701, "alice", "/stats @missing")
    await cmd_stats(message, test_db)

    assert "не найден" in message.reply.call_args[0][0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_top_shows_medals_and_caller_position_outside_top10(test_db) -> None:
    chat_id = -1001234567890
    for idx in range(1, 12):
        user_id = 800 + idx
        nickname = f"user{idx}"
        await test_db.register_user(user_id, nickname)
        await test_db.set_balance(user_id, 1000 - idx * 10)
        await test_db.update_user_group(user_id, chat_id)

    caller_id = 811
    await test_db.set_balance(caller_id, 1)

    message = _message(caller_id, "user11", "/top")
    await cmd_top(message, test_db)

    text = message.reply.call_args[0][0]
    assert "Топ игроков чата" in text
    assert "1. 🥇" in text
    assert "2. 🥈" in text
    assert "3. 🥉" in text
    assert "👤 Ты:" in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_top_rejects_private_chat(test_db) -> None:
    message = _message(999, "private_user", "/top", chat_type="private")
    await cmd_top(message, test_db)
    assert "только в группах" in message.reply.call_args[0][0]
