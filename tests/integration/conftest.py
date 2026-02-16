"""Fixtures for integration tests (real DB, in-memory SQLite)."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from bot.db import Database


@pytest.fixture
async def test_db():
    """Create temporary test database (tables created, cleaned up after test)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    await db.create_tables()
    try:
        yield db
    finally:
        os.unlink(path)


@pytest.fixture
async def test_user(test_db):
    """Ensure test user exists in database; returns user_id."""
    user_id = 123456
    await test_db.get_balance(user_id, 50)  # creates user if missing
    return user_id


@pytest.fixture
def mock_telegram_message():
    """Create mock Telegram message for handler tests."""
    message = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.chat.id = -1001234567890
    message.chat.type = "group"
    message.text = "/start"
    message.answer = AsyncMock()
    message.reply = AsyncMock()
    return message
