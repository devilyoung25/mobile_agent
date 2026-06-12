"""Model options for the dashboard — backed by the model-launcher registry.

The set of selectable models is environment-driven (see
``model_launcher.registry``): Ollama models from ``OLLAMA_MODELS`` plus cloud
models whose provider API key is configured. Use the function forms — the
registry is dynamic, so there are no import-time constant snapshots here.
"""

from __future__ import annotations

from model_launcher import (
    ModelOption,
    default_model_pair,
    model_supports_effort,
    model_supports_images,
    provider_fallback_pair,
    supported_model_ids,
    supported_models,
)

__all__ = [
    "ModelOption",
    "default_model_pair",
    "is_supported_model",
    "model_supports_effort",
    "model_supports_images",
    "provider_fallback_pair",
    "supported_model_ids",
    "supported_models",
]


def is_supported_model(model_id: object) -> bool:
    return isinstance(model_id, str) and model_id in supported_model_ids()
