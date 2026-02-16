"""Fixtures for unit tests (mocks, no real DB/network)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db():
    """Mock database for unit tests."""
    mock = AsyncMock()
    mock.get_balance.return_value = 100
    mock.update_balance.return_value = None
    mock.set_balance.return_value = None
    mock.get_bid.return_value = 1
    mock.get_user.return_value = None
    mock.register_user = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_bot():
    """Mock aiogram bot."""
    mock = MagicMock()
    mock.send_message = AsyncMock()
    mock.answer = AsyncMock()
    return mock


@pytest.fixture
def mock_ai_client():
    """Mock AI client."""
    mock = AsyncMock()
    mock.generate_response.return_value = {
        "content": "Test response",
        "completion_data": {"done": True, "score": 10},
    }
    return mock
