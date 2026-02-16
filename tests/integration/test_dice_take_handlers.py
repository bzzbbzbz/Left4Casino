"""Integration tests for /dice and /take handlers."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bot.config_reader import DiceFightsConfig
from bot.handlers.dice_fight import cmd_dice, cmd_take
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


def _dice_config() -> DiceFightsConfig:
    return DiceFightsConfig(
        challenge_timeout_minutes=5,
        roll_timeout_minutes=5,
        max_debt=100,
        min_bet=1,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dice_success_creates_pending_challenge(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()
    challenge_repo = repo_factory.create_challenge_repo()

    await user_repo.register_user(501, "duelist")
    await user_repo.set_balance(501, 80)

    sent_msg = MagicMock()
    sent_msg.message_id = 777

    message = _group_message(501, "duelist", "/dice 30")
    message.answer = AsyncMock(return_value=sent_msg)

    await cmd_dice(message, SimpleNamespace(args="30"), repo_factory, _dice_config())

    challenge = await challenge_repo.get_active_challenge_by_user(501, message.chat.id)
    assert challenge is not None
    assert challenge["status"] == "pending"
    assert challenge["bet_amount"] == 30

    reply_text = message.answer.call_args[0][0]
    assert "ВЫЗОВ НА ДУЭЛЬ" in reply_text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dice_rejects_when_bet_exceeds_balance_plus_available_debt(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()
    debt_repo = repo_factory.create_debt_repo()
    challenge_repo = repo_factory.create_challenge_repo()

    await user_repo.register_user(501, "duelist")
    await user_repo.register_user(502, "creditor")
    await user_repo.set_balance(501, 10)
    await debt_repo.create_or_update_debt(501, 502, 95, -1001234567890, str(uuid.uuid4()))

    message = _group_message(501, "duelist", "/dice 20")
    await cmd_dice(message, SimpleNamespace(args="20"), repo_factory, _dice_config())

    assert "Максимальная ставка" in message.reply.call_args[0][0]
    challenge = await challenge_repo.get_active_challenge_by_user(501, message.chat.id)
    assert challenge is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_take_success_collects_partial_debt(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()
    debt_repo = repo_factory.create_debt_repo()

    await user_repo.register_user(601, "collector")
    await user_repo.register_user(602, "debtor")
    await user_repo.set_balance(601, 5)
    await user_repo.set_balance(602, 40)
    await debt_repo.create_or_update_debt(602, 601, 30, -1001234567890, "debt-case-1")

    message = _group_message(601, "collector", "/take 20 @debtor")
    await cmd_take(message, SimpleNamespace(args="20 @debtor"), repo_factory)

    debt = await debt_repo.get_debt(-1001234567890, 602, 601)
    assert debt is not None
    assert debt["amount"] == 10
    assert await user_repo.get_balance(601) == 25
    assert await user_repo.get_balance(602) == 20

    reply_text = message.reply.call_args[0][0]
    assert "Остаток долга" in reply_text
    assert "20" in reply_text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_take_rejects_when_no_debt_exists(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(601, "collector")
    await user_repo.register_user(602, "debtor")

    message = _group_message(601, "collector", "/take 20 @debtor")
    await cmd_take(message, SimpleNamespace(args="20 @debtor"), repo_factory)

    assert "ничего не должен" in message.reply.call_args[0][0]
