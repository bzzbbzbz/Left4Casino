"""Global test fixtures."""

import pytest


@pytest.fixture(scope="session")
def test_config():
    """Test configuration."""
    return {
        "db_path": ":memory:",
        "bot_token": "123456:TEST_TOKEN",
        "openrouter_api_key": "test_key",
    }
