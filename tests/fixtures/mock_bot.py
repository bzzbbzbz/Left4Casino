"""Mock aiogram bot for unit tests."""

from unittest.mock import AsyncMock, MagicMock


def make_mock_bot(*, send_message_return=None):
    """Create a mock aiogram Bot with async send_message."""
    mock = MagicMock()
    mock.send_message = AsyncMock(return_value=send_message_return)
    mock.send_document = AsyncMock()
    mock.answer = AsyncMock()
    return mock
