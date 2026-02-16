"""Mock database for unit tests."""

from unittest.mock import AsyncMock


def make_mock_db(*, balance: int = 100):
    """Create a mock Database with common methods as AsyncMock."""
    mock = AsyncMock()
    mock.get_balance = AsyncMock(return_value=balance)
    mock.update_balance = AsyncMock(return_value=None)
    mock.set_balance = AsyncMock(return_value=None)
    mock.get_bid = AsyncMock(return_value=1)
    mock.update_bid = AsyncMock(return_value=None)
    mock.get_user = AsyncMock(return_value=None)
    mock.register_user = AsyncMock(return_value=None)
    return mock
