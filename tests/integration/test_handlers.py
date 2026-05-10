"""Integration tests for bot handlers (end-to-end command flows)."""

import pytest

from bot.config_reader import GameConfig
from bot.handlers import default_commands
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
def test_start_command_is_absent_from_default_router() -> None:
    """/start is intentionally unhandled: no handler function or router registration."""
    assert not hasattr(default_commands, "cmd_start")
    registered_callbacks = [
        handler.callback.__name__
        for handler in default_commands.router.observers["message"].handlers
    ]
    assert "cmd_start" not in registered_callbacks


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
