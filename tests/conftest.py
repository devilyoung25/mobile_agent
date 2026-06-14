"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _model_registry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose the logical ON Model Gateway model to tests."""
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "test-gateway-key")
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_SUBAGENT_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_EFFORTS", "medium")
    monkeypatch.setenv("MODEL_GATEWAY_DEFAULT_EFFORT", "medium")
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "FIREWORKS_API_KEY",
        "OLLAMA_MODELS",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODELS",
        "DEFAULT_MODEL_ID",
        "DEFAULT_MODEL_EFFORT",
        "MODEL_ROUTER_CHAIN",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _reset_gateway_metadata_cache() -> None:
    """Keep the in-process gateway capability cache from leaking across tests."""
    from model_launcher import gateway_metadata

    gateway_metadata.reset_cache()
    yield
    gateway_metadata.reset_cache()
