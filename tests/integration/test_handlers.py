"""Integration tests for bot handlers (end-to-end command flows)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config_reader import GameConfig
from bot.handlers.default_commands import cmd_start
from bot.handlers.group_games import cmd_balance


def _game_config() -> GameConfig:
    return GameConfig(
        starting_points=50,
        send_gameover_sticker=True,
        throttle_time_spin=2,
        throttle_time_other=1,
        throttle_time_top=5,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_command_creates_user(test_db, mock_telegram_message) -> None:
    """Test /start command creates user in database and sends reply."""
    state = MagicMock()
    state.update_data = AsyncMock()
    l10n = MagicMock()
    l10n.format_value = lambda key, opts=None: f"Points: {opts.get('points', 0) if opts else 0}"
    game_config = _game_config()

    await cmd_start(
        mock_telegram_message,
        state,
        l10n,
        game_config,
        test_db,
    )

    user = await test_db.get_user(mock_telegram_message.from_user.id)
    assert user is not None
    assert user.balance == 50
    assert mock_telegram_message.answer.called
    assert "reply_markup" not in mock_telegram_message.answer.call_args.kwargs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_balance_command_shows_correct_balance(test_db, mock_telegram_message) -> None:
    """Test /balance command shows user's balance."""
    user_id = mock_telegram_message.from_user.id
    await test_db.get_balance(user_id, 50)
    await test_db.set_balance(user_id, 100)
    game_config = _game_config()

    await cmd_balance(mock_telegram_message, test_db, game_config)

    reply_text = mock_telegram_message.reply.call_args[0][0]
    assert "100" in reply_text
