from unittest.mock import MagicMock, patch

import pytest
from model_launcher import (
    default_model_pair,
    fallback_model_id_for,
    is_ollama_model_id,
    make_model,
    model_supports_effort,
    supported_model_ids,
    supported_models,
)


def test_ollama_model_id_detection() -> None:
    assert is_ollama_model_id("ollama:qwen3-coder:480b-cloud") is True
    assert is_ollama_model_id("openai:gpt-5.5") is False
    assert is_ollama_model_id(None) is False


def test_registry_lists_ollama_models_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3-coder:480b-cloud, qwen3-coder-next:cloud")
    models = supported_models()
    assert models[0]["id"] == "ollama:qwen3-coder:480b-cloud"
    assert models[1]["id"] == "ollama:qwen3-coder-next:cloud"
    assert "anthropic:claude-opus-4-8" in supported_model_ids()


def test_registry_hides_cloud_models_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "FIREWORKS_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3-coder:480b-cloud")
    assert [m["id"] for m in supported_models()] == ["ollama:qwen3-coder:480b-cloud"]


def test_default_model_pair_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3-coder:480b-cloud")
    monkeypatch.setenv("DEFAULT_MODEL_ID", "ollama:qwen3-coder:480b-cloud")
    assert default_model_pair() == ("ollama:qwen3-coder:480b-cloud", "medium")


def test_default_model_pair_falls_back_to_first_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3-coder:480b-cloud")
    monkeypatch.setenv("DEFAULT_MODEL_ID", "openai:not-a-model")
    assert default_model_pair() == ("ollama:qwen3-coder:480b-cloud", "medium")


def test_ollama_model_supports_only_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", "qwen3-coder:480b-cloud")
    assert model_supports_effort("ollama:qwen3-coder:480b-cloud", "medium") is True
    assert model_supports_effort("ollama:qwen3-coder:480b-cloud", "high") is False


def test_make_model_routes_ollama_to_openai_compatible_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.2")
    monkeypatch.setenv("OLLAMA_MAX_TOKENS", "1234")
    model = MagicMock(name="ollama_model")

    with patch("langchain_openai.ChatOpenAI", return_value=model) as chat_openai:
        assert make_model("ollama:qwen3-coder:480b-cloud", max_tokens=64_000) is model

    chat_openai.assert_called_once_with(
        model="qwen3-coder:480b-cloud",
        api_key="test-key",
        base_url="https://ollama.com/v1",
        temperature=0.2,
        max_tokens=1234,
    )


def test_fallback_requires_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert fallback_model_id_for("anthropic:claude-opus-4-8") == "openai:gpt-5.5"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert fallback_model_id_for("anthropic:claude-opus-4-8") is None
    assert fallback_model_id_for("ollama:qwen3-coder:480b-cloud") is None
