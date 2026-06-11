from unittest.mock import MagicMock, patch

from agent.models.resolver import (
    build_chat_model,
    is_ollama_model_id,
    strip_ollama_model_prefix,
)


def test_ollama_model_id_detection_and_strip() -> None:
    assert is_ollama_model_id("ollama-local:gpt-oss:120b-cloud") is True
    assert is_ollama_model_id("ollama-cloud:llama3.3") is True
    assert is_ollama_model_id("openai:gpt-5.5") is False
    assert strip_ollama_model_prefix("ollama-local:gpt-oss:120b-cloud") == "gpt-oss:120b-cloud"


def test_build_chat_model_routes_ollama_to_openai_compatible_client(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1234")
    model = MagicMock(name="ollama_model")

    with patch("agent.models.resolver.ChatOpenAI", return_value=model) as chat_openai:
        assert (
            build_chat_model("ollama-local:gpt-oss:120b-cloud", "high", max_tokens=64_000)
            is model
        )

    chat_openai.assert_called_once_with(
        model="gpt-oss:120b-cloud",
        api_key="test-key",
        base_url="http://127.0.0.1:11434/v1",
        temperature=0.2,
        max_tokens=1234,
    )


def test_build_chat_model_preserves_supported_provider_kwargs() -> None:
    model = MagicMock(name="provider_model")
    factory = MagicMock(return_value=model)

    assert build_chat_model(
        "anthropic:claude-opus-4-8",
        "high",
        max_tokens=16_000,
        model_factory=factory,
    ) is model

    factory.assert_called_once_with(
        "anthropic:claude-opus-4-8",
        max_tokens=16_000,
        thinking={"type": "adaptive", "display": "summarized"},
        effort="high",
    )

