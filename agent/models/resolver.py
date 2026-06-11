"""Resolve chat model instances, including custom OpenAI-compatible providers.

NOTE (deferred): this Ollama-compatible resolver is NOT yet wired into the
runtime. ``agent/server.py`` still builds models via ``make_model`` /
``provider_model_kwargs`` directly, and ``ollama-local:`` / ``ollama-cloud:``
ids are not in ``SUPPORTED_MODEL_IDS`` or the dashboard options. Ollama does
not work end-to-end yet — wiring it in is tracked as separate follow-up work.
This module and its unit tests exist so the resolution logic is ready to drop
in, not as a claim that the path is live.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.utils.model import make_model, provider_model_kwargs

OLLAMA_MODEL_PREFIXES = ("ollama-local:", "ollama-cloud:")


def is_ollama_model_id(model_id: str | None) -> bool:
    """Return whether the model id should use the Ollama-compatible route."""
    return isinstance(model_id, str) and model_id.startswith(OLLAMA_MODEL_PREFIXES)


def strip_ollama_model_prefix(model_id: str) -> str:
    """Remove the routing prefix while preserving the full Ollama model name."""
    for prefix in OLLAMA_MODEL_PREFIXES:
        if model_id.startswith(prefix):
            return model_id.removeprefix(prefix)
    return model_id


def build_chat_model(
    model_id: str,
    effort: str | None,
    *,
    max_tokens: int,
    model_factory: Callable[..., BaseChatModel] = make_model,
) -> BaseChatModel:
    """Build the chat model for supported providers or Ollama-compatible ids."""
    if is_ollama_model_id(model_id):
        return ChatOpenAI(
            model=strip_ollama_model_prefix(model_id),
            api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0")),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", str(max_tokens))),
        )

    model_kwargs: dict[str, Any] = provider_model_kwargs(
        model_id,
        effort or "medium",
        max_tokens=max_tokens,
    )
    return model_factory(model_id, **model_kwargs)

