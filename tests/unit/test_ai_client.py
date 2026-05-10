"""Unit tests for AIClient provider routing and greeting fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import AIConfig
from bot.services.ai import DEFAULT_AI_TIMEOUT_SECONDS, AIClient, AIServiceError

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
        timeout=DEFAULT_AI_TIMEOUT_SECONDS,
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
async def test_real_ai_error_raises_sanitized_greeting_error(monkeypatch) -> None:
    """Real provider errors must not degrade to fake greeting fallback."""
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
        with pytest.raises(AIServiceError, match="AI greeting generation failed"):
            await client.generate_initial_greeting()

    create.assert_awaited_once()


@pytest.mark.parametrize(
    "placeholder",
    [
        "",
        "   ",
        "dummy",
        "replace-me",
        "changeme",
        "your-api-key",
        "your_api_key",
        "your-openrouter-api-key",
        "<OPENROUTER_API_KEY>",
        "placeholder",
    ],
)
def test_real_provider_rejects_placeholder_api_keys(monkeypatch, placeholder: str) -> None:
    """Real providers fail fast for template placeholders, without affecting mock."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="requires a real API key"):
        AIClient(AIConfig(provider="openrouter", api_key=placeholder, model="test/model"))


def test_mock_provider_allows_placeholder_api_key(monkeypatch) -> None:
    """Explicit mock remains usable without real credentials."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("bot.services.ai.AsyncOpenAI") as openai_cls:
        client = AIClient(AIConfig(provider="mock", api_key="replace-me", model="unused"))

    assert client.provider == "mock"
    openai_cls.assert_not_called()


@pytest.mark.asyncio
async def test_greeting_error_log_omits_raw_exception_message(monkeypatch, caplog) -> None:
    """LLM exception logs must not include secret-bearing raw exception text."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(side_effect=RuntimeError("secret sk-test-secret leaked context"))
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(provider="openai", api_key="test-openai-key", model="gpt-4o-mini")
        )
        with pytest.raises(AIServiceError, match="AI greeting generation failed"):
            await client.generate_initial_greeting()

    assert "RuntimeError" in caplog.records[-1].__dict__.get("error_type", "")
    assert "sk-test-secret" not in caplog.text
    assert "leaked context" not in caplog.text


@pytest.mark.asyncio
async def test_real_response_error_raises_without_fake_credit(monkeypatch) -> None:
    """Real provider response errors must not return fake completion_data."""
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
        with pytest.raises(AIServiceError, match="AI response generation failed"):
            await client.generate_response([{"role": "user", "content": "ответ"}])

    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_response_invalid_json_raises_without_fake_credit(monkeypatch) -> None:
    """Invalid real-provider response must not be converted into a credit grant."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(return_value=_chat_response("not json"))
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(provider="openai", api_key="test-openai-key", model="gpt-4o-mini")
        )
        with pytest.raises(AIServiceError, match="invalid JSON"):
            await client.generate_response([{"role": "user", "content": "ответ"}])

    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_response_valid_schema_returns_completion(monkeypatch) -> None:
    """Valid real-provider JSON is normalized into handler response data."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(
        return_value=_chat_response(
            '{"content":"Держи, заслужил",'
            '"completion_data":{"done":true,"score":77,"reward":42,"comment":"годно"}}'
        )
    )
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(provider="openai", api_key="test-openai-key", model="gpt-4o-mini")
        )
        response = await client.generate_response([{"role": "user", "content": "ответ"}])

    assert response == {
        "content": "Держи, заслужил",
        "completion_data": {"done": True, "score": 77, "reward": 42, "comment": "годно"},
    }
    create.assert_awaited_once()


@pytest.mark.parametrize(
    ("payload", "case"),
    [
        (
            '{"completion_data":{"done":true,"score":77,"reward":42,"comment":"ok"}}',
            "missing content",
        ),
        (
            '{"content":"ok","completion_data":{"done":true,"score":77,"comment":"ok"}}',
            "missing reward",
        ),
        (
            '{"content":"ok","completion_data":{"done":true,"score":77,"reward":"many","comment":"ok"}}',
            "non-numeric reward",
        ),
        ('{"content":"ok","reward":42}', "missing completion_data"),
        ('{"content":"ok","completion_data":"bad"}', "malformed completion_data"),
        (
            '{"content":"ok","completion_data":{"done":"yes","score":77,"reward":42,"comment":"ok"}}',
            "bad done",
        ),
    ],
)
@pytest.mark.asyncio
async def test_real_response_malformed_schema_raises_without_fake_credit(
    monkeypatch, payload: str, case: str
) -> None:
    """Malformed real-provider JSON must fail closed instead of defaulting fields."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = AsyncMock(return_value=_chat_response(payload))
    openai_cls = MagicMock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
    )

    with patch("bot.services.ai.AsyncOpenAI", openai_cls):
        client = AIClient(
            AIConfig(provider="openai", api_key="test-openai-key", model="gpt-4o-mini")
        )
        with pytest.raises(AIServiceError, match="malformed schema"):
            await client.generate_response([{"role": "user", "content": case}])

    create.assert_awaited_once()
