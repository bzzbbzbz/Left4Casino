"""Unit tests for AIClient provider routing and greeting fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import AIConfig
from bot.services.ai import AIClient

pytestmark = pytest.mark.unit


def _chat_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.asyncio
async def test_openrouter_provider_uses_llm_greeting_with_config_api_key(monkeypatch) -> None:
    """OpenRouter provider must use OpenRouter endpoint even when key is from config."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(return_value=_chat_response("Сгенерированное задание"))
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(
                provider="openrouter",
                api_key="test-openrouter-key",
                model="deepseek/deepseek-chat",
            )
        )
        greeting = await client.generate_initial_greeting()

    assert greeting == "Сгенерированное задание"
    openai_cls.assert_called_once_with(
        base_url="https://openrouter.ai/api/v1",
        api_key="test-openrouter-key",
    )
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_mock_provider_uses_local_fallback_without_llm(monkeypatch) -> None:
    """Only explicit mock provider should use local greeting without constructing LLM client."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("bot.services.ai.AsyncOpenAI") as openai_cls:
        client = AIClient(AIConfig(provider="mock", api_key="dummy", model="unused"))
        greeting = await client.generate_initial_greeting()

    assert greeting == "Эй, ты! Хочешь денег? Удиви меня!"
    openai_cls.assert_not_called()


@pytest.mark.asyncio
async def test_real_ai_error_uses_safe_greeting_fallback(monkeypatch) -> None:
    """Real provider errors are allowed to degrade to safe non-secret fallback."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(side_effect=RuntimeError("upstream unavailable"))
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(provider="openai", api_key="test-openai-key", model="gpt-4o-mini")
        )
        greeting = await client.generate_initial_greeting()

    assert greeting == "Эй, ты! Хочешь денег? Удиви меня!"
    create.assert_awaited_once()
