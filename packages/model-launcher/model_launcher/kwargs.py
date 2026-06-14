"""OpenAI-compatible gateway chat-model construction.

The AgentEngine does not route providers directly. It talks to one logical
model endpoint and the external ON Model Gateway owns provider selection,
downgrades, rate limits, and transient errors.
"""

from __future__ import annotations

import os
from typing import TypedDict

DEFAULT_GATEWAY_MODEL = "on-auto-coder"
DEFAULT_GATEWAY_EFFORT = "medium"
DEFAULT_GATEWAY_TEMPERATURE = 0.0
DEFAULT_GATEWAY_MAX_TOKENS = 64_000


class ModelKwargs(TypedDict, total=False):
    max_tokens: int | None
    temperature: float | None


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def gateway_base_url() -> str:
    base_url = _env("MODEL_GATEWAY_BASE_URL").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "MODEL_GATEWAY_BASE_URL is required. Start ON Model Gateway first "
            "and set MODEL_GATEWAY_BASE_URL, e.g. http://localhost:4000/v1."
        )
    return base_url


def gateway_api_key() -> str:
    return _env("MODEL_GATEWAY_API_KEY") or "on-mobile-agent"


def gateway_temperature() -> float:
    raw = _env("MODEL_GATEWAY_TEMPERATURE")
    if not raw:
        return DEFAULT_GATEWAY_TEMPERATURE
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError("MODEL_GATEWAY_TEMPERATURE must be a number") from exc


def gateway_max_tokens(default: int = DEFAULT_GATEWAY_MAX_TOKENS) -> int:
    raw = _env("MODEL_GATEWAY_MAX_TOKENS")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError("MODEL_GATEWAY_MAX_TOKENS must be an integer") from exc


def make_model(
    model_id: str,
    *,
    profile: dict[str, object] | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
):
    """Build a chat model backed by the external OpenAI-compatible gateway.

    Per-model capabilities (context window, output cap, reasoning effort, image
    support) are discovered from gateway metadata and threaded in by the caller:

    - ``profile`` is a langchain ``ModelProfile`` dict; its ``max_input_tokens``
      drives the summarization/context-window trigger (deepagents reads it).
    - ``reasoning_effort`` is sent to the gateway only when the model advertises
      support for it (validated by the caller).
    - ``max_tokens`` (output) precedence: gateway ``max_output_tokens`` >
      explicit ``max_tokens`` arg > ``MODEL_GATEWAY_MAX_TOKENS`` env > default.
    """
    from langchain_openai import ChatOpenAI

    if max_output_tokens is not None:
        resolved_max_tokens = max_output_tokens
    elif max_tokens is not None:
        resolved_max_tokens = max_tokens
    else:
        resolved_max_tokens = gateway_max_tokens()

    kwargs: dict[str, object] = {
        "model": model_id,
        "api_key": gateway_api_key(),
        "base_url": gateway_base_url(),
        "temperature": temperature if temperature is not None else gateway_temperature(),
        "max_tokens": resolved_max_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    if profile:
        kwargs["profile"] = profile
    return ChatOpenAI(**kwargs)
