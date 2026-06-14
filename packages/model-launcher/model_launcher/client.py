"""Gateway-backed model launcher.

This package intentionally exposes only logical model ids. Provider routing is
externalized to ON Model Gateway. Per-model capabilities (context window, output
cap, reasoning effort) are discovered from gateway metadata and applied here when
the concrete models are built.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from . import gateway_metadata
from .gateway_metadata import GatewayModel
from .kwargs import DEFAULT_GATEWAY_MAX_TOKENS, make_model


@dataclass(frozen=True)
class ModelLaunchPlan:
    model: BaseChatModel
    subagent_model: BaseChatModel
    model_id: str
    effort: str | None


def _build_model(
    model_id: str,
    effort: str | None,
    caps: dict[str, GatewayModel],
    fallback_max_tokens: int,
) -> BaseChatModel:
    cap = caps.get(model_id)
    profile = cap.to_profile() if cap is not None else None
    # Only transmit reasoning_effort when the model advertises that effort —
    # otherwise the gateway may reject an unsupported field.
    resolved_effort = effort if (cap is not None and effort and effort in cap.efforts) else None
    max_output_tokens = cap.max_output_tokens if cap is not None else None
    return make_model(
        model_id,
        profile=profile,
        reasoning_effort=resolved_effort,
        max_output_tokens=max_output_tokens,
        max_tokens=fallback_max_tokens,
    )


class ModelLauncherClient:
    """Build model instances against the configured model gateway."""

    def create_plan(
        self,
        *,
        model_id: str,
        effort: str | None,
        subagent_model_id: str,
        subagent_effort: str | None,
        models: list[GatewayModel] | None = None,
        max_tokens: int = DEFAULT_GATEWAY_MAX_TOKENS,
    ) -> ModelLaunchPlan:
        catalog = models if models is not None else gateway_metadata.snapshot()
        caps = {model.id: model for model in catalog}
        return ModelLaunchPlan(
            model=_build_model(model_id, effort, caps, max_tokens),
            subagent_model=_build_model(subagent_model_id, subagent_effort, caps, max_tokens),
            model_id=model_id,
            effort=effort,
        )


def create_model_plan(
    *,
    model_id: str,
    effort: str | None,
    subagent_model_id: str,
    subagent_effort: str | None,
    models: list[GatewayModel] | None = None,
    max_tokens: int = DEFAULT_GATEWAY_MAX_TOKENS,
) -> ModelLaunchPlan:
    return ModelLauncherClient().create_plan(
        model_id=model_id,
        effort=effort,
        subagent_model_id=subagent_model_id,
        subagent_effort=subagent_effort,
        models=models,
        max_tokens=max_tokens,
    )
