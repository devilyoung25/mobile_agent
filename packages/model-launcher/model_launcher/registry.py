"""Logical model registry for ON Model Gateway.

This is the single API surface every consumer uses (dashboard ``/options``, team
settings, profiles, schedules, thread validation, model construction). It is a
thin projection over the gateway capability snapshot
(:mod:`model_launcher.gateway_metadata`) — the gateway owns the catalog and the
per-model capabilities; this module just exposes them in the shapes callers
expect. No provider routing and no direct env parsing live here.
"""

from __future__ import annotations

import os
from typing import TypedDict

from . import gateway_metadata
from .gateway_metadata import GatewayModel
from .kwargs import DEFAULT_GATEWAY_EFFORT, DEFAULT_GATEWAY_MODEL


class ModelOption(TypedDict):
    id: str
    label: str
    efforts: list[str]
    default_effort: str
    supports_images: bool


def _to_option(model: GatewayModel) -> ModelOption:
    return {
        "id": model.id,
        "label": model.label,
        "efforts": list(model.efforts),
        "default_effort": model.default_effort,
        "supports_images": model.supports_images,
    }


def supported_models() -> list[ModelOption]:
    return [_to_option(model) for model in gateway_metadata.snapshot()]


def supported_model_ids() -> frozenset[str]:
    return frozenset(model.id for model in gateway_metadata.snapshot())


def _find(model_id: str) -> GatewayModel | None:
    for model in gateway_metadata.snapshot():
        if model.id == model_id:
            return model
    return None


def model_supports_effort(model_id: str, effort: str) -> bool:
    option = _find(model_id)
    return option is not None and effort in option.efforts


def model_supports_images(model_id: str) -> bool:
    option = _find(model_id)
    return option is not None and option.supports_images


def default_effort_for_model(model_id: str, preferred_effort: object = None) -> str:
    option = _find(model_id)
    if option is None:
        return DEFAULT_GATEWAY_EFFORT
    if isinstance(preferred_effort, str) and preferred_effort in option.efforts:
        return preferred_effort
    return option.default_effort


def provider_fallback_pair(_model_id: object, _effort: object = None) -> tuple[str, str] | None:
    """No in-repo provider fallback. Gateway owns routing and downgrades."""
    return None


def default_model_pair() -> tuple[str, str]:
    model = os.environ.get("MODEL_GATEWAY_MODEL", DEFAULT_GATEWAY_MODEL).strip() or DEFAULT_GATEWAY_MODEL
    return model, default_effort_for_model(model, os.environ.get("MODEL_GATEWAY_DEFAULT_EFFORT"))


def default_subagent_model_pair() -> tuple[str, str]:
    model = os.environ.get("MODEL_GATEWAY_SUBAGENT_MODEL", "").strip() or default_model_pair()[0]
    return model, default_effort_for_model(model, os.environ.get("MODEL_GATEWAY_DEFAULT_EFFORT"))


def default_model_id() -> str:
    return default_model_pair()[0]
