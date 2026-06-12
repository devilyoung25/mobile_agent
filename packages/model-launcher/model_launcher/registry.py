"""Model registry: which models are available, driven by configured backends.

Cloud catalog entries only surface when their provider API key is present in
the environment; Ollama entries come from ``OLLAMA_MODELS``. The dashboard's
selector, profile validation, and the engine's per-thread override checks all
read from this registry, so a model that cannot authenticate never appears.
"""

from __future__ import annotations

import os
from typing import TypedDict

from .kwargs import _provider_key_present


class ModelOption(TypedDict):
    id: str
    label: str
    efforts: list[str]
    default_effort: str
    supports_images: bool


_CLOUD_CATALOG: list[ModelOption] = [
    {
        "id": "anthropic:claude-opus-4-8",
        "label": "Opus 4.8",
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "default_effort": "high",
        "supports_images": True,
    },
    {
        "id": "openai:gpt-5.5",
        "label": "GPT-5.5",
        "efforts": ["none", "low", "medium", "high", "xhigh"],
        "default_effort": "xhigh",
        "supports_images": True,
    },
    {
        "id": "google_genai:gemini-3.5-flash",
        "label": "Gemini 3.5 Flash",
        "efforts": ["minimal", "low", "medium", "high"],
        "default_effort": "medium",
        "supports_images": True,
    },
    {
        "id": "fireworks:accounts/fireworks/models/kimi-k2p6",
        "label": "Kimi K2.6",
        "efforts": ["none", "low", "medium", "high"],
        "default_effort": "high",
        "supports_images": False,
    },
    {
        "id": "fireworks:accounts/fireworks/models/deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "efforts": ["none", "low", "medium", "high", "xhigh", "max"],
        "default_effort": "high",
        "supports_images": False,
    },
    {
        "id": "fireworks:accounts/fireworks/models/glm-5p1",
        "label": "GLM 5.1",
        "efforts": ["none", "low", "medium", "high"],
        "default_effort": "high",
        "supports_images": False,
    },
]

_OLLAMA_EFFORTS = ["medium"]


def _provider_of(model_id: str) -> str | None:
    provider, _, rest = model_id.partition(":")
    return provider if rest else None


def _ollama_models_from_env() -> list[ModelOption]:
    raw = os.environ.get("OLLAMA_MODELS", "")
    options: list[ModelOption] = []
    for name in raw.split(","):
        name = name.strip()
        if not name:
            continue
        options.append(
            {
                "id": f"ollama:{name}",
                "label": f"Ollama · {name}",
                "efforts": list(_OLLAMA_EFFORTS),
                "default_effort": "medium",
                "supports_images": False,
            }
        )
    return options


def supported_models() -> list[ModelOption]:
    """Models the deployment can actually serve, Ollama first when configured."""
    models = _ollama_models_from_env()
    for option in _CLOUD_CATALOG:
        provider = _provider_of(option["id"])
        if provider and _provider_key_present(provider):
            models.append(option)
    return models


def supported_model_ids() -> frozenset[str]:
    return frozenset(m["id"] for m in supported_models())


def _find(model_id: str) -> ModelOption | None:
    for m in supported_models():
        if m["id"] == model_id:
            return m
    return None


def model_supports_effort(model_id: str, effort: str) -> bool:
    option = _find(model_id)
    return option is not None and effort in option["efforts"]


def model_supports_images(model_id: str) -> bool:
    option = _find(model_id)
    return option is not None and option["supports_images"]


def _fallback_effort_for(model: ModelOption, effort: object) -> str | None:
    if not isinstance(effort, str):
        return None
    if effort in model["efforts"]:
        return effort
    if (
        model["id"].startswith("google_genai:")
        and effort == "none"
        and "minimal" in model["efforts"]
    ):
        return "minimal"
    return None


def provider_fallback_pair(model_id: object, effort: object = None) -> tuple[str, str] | None:
    """Newest supported ``(model_id, effort)`` for the same provider as ``model_id``.

    Keeps a stored selection on its original provider when its exact id has
    dropped out of the supported set, instead of falling through to the
    cross-provider global default. Returns ``None`` when no supported model
    shares the provider.
    """
    if not isinstance(model_id, str):
        return None
    provider = _provider_of(model_id)
    if provider is None:
        return None
    for m in supported_models():
        if _provider_of(m["id"]) == provider:
            return m["id"], _fallback_effort_for(m, effort) or m["default_effort"]
    return None


def default_model_pair() -> tuple[str, str]:
    """The deployment's default ``(model_id, reasoning_effort)``.

    ``DEFAULT_MODEL_ID``/``DEFAULT_MODEL_EFFORT`` env vars win when they name an
    available model; otherwise the first available model is used.
    """
    env_model = os.environ.get("DEFAULT_MODEL_ID", "").strip()
    env_effort = os.environ.get("DEFAULT_MODEL_EFFORT", "").strip()
    if env_model:
        option = _find(env_model)
        if option is not None:
            effort = env_effort if env_effort in option["efforts"] else option["default_effort"]
            return env_model, effort
    models = supported_models()
    if not models:
        raise RuntimeError(
            "No models available: set OLLAMA_MODELS or a provider API key "
            "(ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY / FIREWORKS_API_KEY)"
        )
    first = models[0]
    return first["id"], first["default_effort"]


def default_model_id() -> str:
    return default_model_pair()[0]
