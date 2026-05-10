"""Unit tests for /credit handler AI greeting behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import AIConfig
from bot.handlers.ai_credit import cmd_credit

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_credit_sends_generated_greeting_without_handler_fallback() -> None:
    """When AIClient succeeds, /credit must send its greeting unchanged."""
    db = AsyncMock()
    db.get_balance = AsyncMock(return_value=0)
    db.get_active_session = AsyncMock(return_value=None)
    db.get_last_credit_event = AsyncMock(return_value=None)
    db.create_credit_session = AsyncMock()
    db.update_user_state = AsyncMock()
    db.add_dialogue_message = AsyncMock()

    ai_client = AsyncMock()
    ai_client.generate_initial_greeting = AsyncMock(return_value="Сгенерированное задание")

    message = MagicMock()
    message.from_user.id = 123456
    message.reply = AsyncMock()

    await cmd_credit(
        message,
        db,
        ai_client,
        AIConfig(provider="openrouter", api_key="test-key", model="test-model"),
    )

    ai_client.generate_initial_greeting.assert_awaited_once()
    db.add_dialogue_message.assert_awaited_once()
    message.reply.assert_awaited_once_with("Сгенерированное задание")
    sent_text = message.reply.await_args.args[0]
    assert sent_text != "Банкир сейчас на обеде. Попробуй зайти позже."
    assert sent_text != "Эй, ты! Хочешь денег? Удиви меня!"


@pytest.mark.asyncio
async def test_credit_greeting_failure_closes_session_and_sanitizes_log() -> None:
    """Greeting failures must close the created session and avoid raw error logging."""
    db = AsyncMock()
    db.get_balance = AsyncMock(return_value=0)
    db.get_active_session = AsyncMock(return_value=None)
    db.get_last_credit_event = AsyncMock(return_value=None)
    db.create_credit_session = AsyncMock()
    db.update_user_state = AsyncMock()
    db.add_dialogue_message = AsyncMock()
    db.close_credit_session = AsyncMock()

    ai_client = AsyncMock()
    ai_client.generate_initial_greeting = AsyncMock(
        side_effect=RuntimeError("secret sk-test-secret request context")
    )

    message = MagicMock()
    message.from_user.id = 123456
    message.reply = AsyncMock()
    logger = AsyncMock()

    with patch("bot.handlers.ai_credit.logger", logger):
        await cmd_credit(
            message,
            db,
            ai_client,
            AIConfig(provider="openrouter", api_key="test-key", model="test-model"),
        )

    session_id = db.create_credit_session.await_args.args[0]
    db.close_credit_session.assert_awaited_once_with(session_id, "failed", 0, 0)
    db.update_user_state.assert_awaited_with(123456, "IDLE")
    message.reply.assert_awaited_once_with("Банкир сейчас на обеде. Попробуй зайти позже.")
    logger.aerror.assert_awaited_once_with("AI Error during greeting", error_type="RuntimeError")
