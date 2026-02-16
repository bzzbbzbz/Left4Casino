"""Integration tests for /give and /safe handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
from bot.handlers.safe import cmd_safe
from bot.handlers.transfer import cmd_give
from bot.repositories import RepositoryFactory


def _group_message(user_id: int, username: str, text: str) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.from_user.first_name = username
    message.chat.id = -1001234567890
    message.chat.type = "group"
    message.text = text
    message.reply_to_message = None
    message.answer = AsyncMock()
    message.reply = AsyncMock()
    return message


async def _event_types(db_path: str, user_id: int) -> list[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT event_type FROM event_history WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [row[0] for row in rows]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_give_success_updates_balances_and_events(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(101, "sender")
    await user_repo.register_user(202, "target")
    await user_repo.set_balance(101, 100)
    await user_repo.set_balance(202, 10)

    message = _group_message(101, "sender", "/give 30 @target")
    await cmd_give(message, SimpleNamespace(args="30 @target"), repo_factory)

    assert await user_repo.get_balance(101) == 70
    assert await user_repo.get_balance(202) == 40

    sender_events = await _event_types(test_db.db_path, 101)
    target_events = await _event_types(test_db.db_path, 202)
    assert "transfer_out" in sender_events
    assert "transfer_in" in target_events
    assert message.answer.call_args[0][0].startswith("✅ Успешно передано 30")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_give_rejects_when_insufficient_funds(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(101, "sender")
    await user_repo.register_user(202, "target")
    await user_repo.set_balance(101, 5)
    await user_repo.set_balance(202, 10)

    message = _group_message(101, "sender", "/give 30 @target")
    await cmd_give(message, SimpleNamespace(args="30 @target"), repo_factory)

    assert await user_repo.get_balance(101) == 5
    assert await user_repo.get_balance(202) == 10
    assert "Недостаточно средств" in message.answer.call_args[0][0]

    sender_events = await _event_types(test_db.db_path, 101)
    assert "transfer_out" not in sender_events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safe_deposit_success_updates_main_and_safe_balances(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(303, "safeuser")
    await user_repo.set_balance(303, 100)

    message = _group_message(303, "safeuser", "/safe 25")
    await cmd_safe(message, SimpleNamespace(args="25"), repo_factory)

    assert await user_repo.get_balance(303) == 75
    assert await user_repo.get_safe_balance(303) == 25
    assert "✅ Положено в сейф: 25 очков" in message.answer.call_args[0][0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_safe_rejects_deposit_during_active_challenge(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()
    challenge_repo = repo_factory.create_challenge_repo()

    await user_repo.register_user(303, "safeuser")
    await user_repo.register_user(404, "enemy")
    await user_repo.set_balance(303, 100)

    await challenge_repo.create_dice_challenge(
        challenge_id="challenge-safe-lock",
        chat_id=-1001234567890,
        initiator_id=303,
        nickname="safeuser",
        first_name="safeuser",
        bet=10,
        going_debt=False,
        message_id=1,
    )

    message = _group_message(303, "safeuser", "/safe 25")
    await cmd_safe(message, SimpleNamespace(args="25"), repo_factory)

    assert await user_repo.get_balance(303) == 100
    assert await user_repo.get_safe_balance(303) == 0
    assert "Нельзя класть в сейф" in message.answer.call_args[0][0]
