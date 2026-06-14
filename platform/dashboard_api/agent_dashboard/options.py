"""Model options for the dashboard — backed by ON Model Gateway registry."""

from __future__ import annotations

from model_launcher import (
    ModelOption,
    default_model_pair,
    default_subagent_model_pair,
    get_gateway_models,
    model_supports_effort,
    model_supports_images,
    provider_fallback_pair,
    supported_model_ids,
    supported_models,
)

__all__ = [
    "ModelOption",
    "default_model_pair",
    "default_subagent_model_pair",
    "get_gateway_models",
    "is_supported_model",
    "model_supports_effort",
    "model_supports_images",
    "provider_fallback_pair",
    "supported_model_ids",
    "supported_models",
]


def is_supported_model(model_id: object) -> bool:
    return isinstance(model_id, str) and model_id in supported_model_ids()
