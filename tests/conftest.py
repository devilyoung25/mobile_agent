"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _model_registry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose the full cloud model catalog to tests.

    The model registry is environment-driven (provider API keys gate which
    models surface). Tests exercise selector/validation logic against the
    cloud catalog, so stub every provider key; Ollama stays unset unless a
    test opts in via ``OLLAMA_MODELS``.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-fireworks-key")
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL_ID", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL_EFFORT", raising=False)
