"""Model-resolution for agent composition.

Resolves the per-run model plan: team defaults → dashboard profile overrides →
per-thread override, then applies gateway capabilities via ``create_model_plan``.
Extracted from ``agent/server.py`` without behaviour change. ``team_defaults`` and
``profile`` are awaited by the caller (in parallel with sandbox setup) and passed in.
"""

from __future__ import annotations

import logging
from typing import Any

from ..dashboard.agent_overrides import (
    normalize_profile_overrides,
    normalize_profile_subagent_overrides,
)
from ..dashboard.options import is_supported_model, model_supports_effort
from ..utils.model import create_model_plan, get_gateway_models

logger = logging.getLogger(__name__)

DEFAULT_LLM_MAX_TOKENS = 64_000


async def resolve_model_plan(
    actor_id: str | None,
    profile: dict[str, Any] | None,
    team_defaults: tuple[tuple[str, str], tuple[str, str]],
    configurable: dict[str, Any],
) -> tuple[Any, str, str]:
    """Resolve the model plan: team defaults → profile override → per-thread override.

    Returns ``(model_plan, model_id, profile_effort)``. ``model_id``/``profile_effort``
    are surfaced for usage logging and thread metadata.
    """
    (model_id, profile_effort), (subagent_model_id, subagent_effort) = team_defaults
    logger.info("Using team default agent model: model=%s effort=%s", model_id, profile_effort)
    logger.info(
        "Using team default agent subagent model: model=%s effort=%s",
        subagent_model_id,
        subagent_effort,
    )

    if actor_id and profile:
        overridden_model, overridden_effort = normalize_profile_overrides(profile)
        if overridden_model:
            logger.info(
                "Applying dashboard profile override for %s: model=%s effort=%s",
                actor_id,
                overridden_model,
                overridden_effort,
            )
            model_id = overridden_model
            profile_effort = overridden_effort
            subagent_model_id = overridden_model
            subagent_effort = overridden_effort
        overridden_subagent_model, overridden_subagent_effort = (
            normalize_profile_subagent_overrides(profile)
        )
        if overridden_subagent_model:
            logger.info(
                "Applying dashboard profile subagent override for %s: model=%s effort=%s",
                actor_id,
                overridden_subagent_model,
                overridden_subagent_effort,
            )
            subagent_model_id = overridden_subagent_model
            subagent_effort = overridden_subagent_effort

    per_thread_model = configurable.get("agent_model_id")
    per_thread_effort = configurable.get("agent_effort")
    if (
        isinstance(per_thread_model, str)
        and is_supported_model(per_thread_model)
        and isinstance(per_thread_effort, str)
        and model_supports_effort(per_thread_model, per_thread_effort)
    ):
        logger.info(
            "Applying per-thread model override: model=%s effort=%s",
            per_thread_model,
            per_thread_effort,
        )
        model_id = per_thread_model
        profile_effort = per_thread_effort
        subagent_model_id = per_thread_model
        subagent_effort = per_thread_effort

    # Discover per-model capabilities from the gateway (cached, async) and apply
    # them: context window -> summarization trigger, reasoning effort, output cap.
    gateway_models = await get_gateway_models()
    model_plan = create_model_plan(
        model_id=model_id,
        effort=profile_effort,
        subagent_model_id=subagent_model_id,
        subagent_effort=subagent_effort,
        models=gateway_models,
        max_tokens=DEFAULT_LLM_MAX_TOKENS,
    )
    return model_plan, model_id, profile_effort


__all__ = ["DEFAULT_LLM_MAX_TOKENS", "resolve_model_plan"]
