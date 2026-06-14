"""Brand-free deep-agent assembly: the engine's only job.

``build_engine`` knows nothing about identity providers, code hosts, or
model brands. It receives already-constructed models, an already-filtered
tool list, an already-rendered system prompt, and a sandbox backend factory
— and wires the standard middleware stack around them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, SubAgent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel

from .middleware import (
    ModelFallbackMiddleware,
    SandboxCircuitBreakerMiddleware,
    SanitizeThinkingBlocksMiddleware,
    SanitizeToolInputsMiddleware,
    ToolArtifactMiddleware,
    ToolErrorMiddleware,
    check_message_queue_before_model,
    ensure_no_empty_msg,
)

DEFAULT_RECURSION_LIMIT = 9_999
MODEL_CALL_RECURSION_LIMIT = 5_000  # ~half the recursion limit to account for tool calls


def general_purpose_subagent(model: BaseChatModel) -> SubAgent:
    return {
        "name": GENERAL_PURPOSE_SUBAGENT["name"],
        "description": GENERAL_PURPOSE_SUBAGENT["description"],
        "system_prompt": GENERAL_PURPOSE_SUBAGENT["system_prompt"],
        "model": model,
    }


def build_engine(
    *,
    model: BaseChatModel,
    subagent_model: BaseChatModel,
    system_prompt: str,
    tools: Sequence[Any],
    backend: Callable[..., Any] | Any,
    fallback_model: BaseChatModel | None = None,
    run_limit: int = MODEL_CALL_RECURSION_LIMIT,
    approval_policy: dict[str, Any] | None = None,
):
    """Assemble the deep agent with the engine's standard middleware stack.

    ``approval_policy`` is the brand-neutral human-approval gate: a mapping of tool
    name to ``bool``/``InterruptOnConfig`` (langchain's ``HumanInTheLoopMiddleware``
    ``interrupt_on``). When provided, a tool call matching the policy pauses the run
    via ``interrupt()`` until a human approves/rejects it. The engine knows nothing
    about *which* actions need approval — the composition layer supplies the policy.
    """
    fallback_middleware = [ModelFallbackMiddleware(fallback_model)] if fallback_model else []
    # Place the gate right after input sanitization so it interrupts on the
    # cleaned tool call, before execution (ToolError/ToolArtifact) wrapping.
    approval_middleware = (
        [HumanInTheLoopMiddleware(approval_policy)] if approval_policy else []
    )
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        tools=list(tools),
        subagents=[general_purpose_subagent(subagent_model)],
        backend=backend,
        middleware=[
            SanitizeToolInputsMiddleware(),
            *approval_middleware,
            ModelCallLimitMiddleware(run_limit=run_limit, exit_behavior="end"),
            ToolErrorMiddleware(),
            ToolArtifactMiddleware(),
            # Drains follow-up messages queued mid-run (Store ("queue", thread_id))
            # and injects them before the next model call. Upstream placed it here,
            # right after ToolArtifactMiddleware and before ensure_no_empty_msg.
            check_message_queue_before_model,
            ensure_no_empty_msg,
            SandboxCircuitBreakerMiddleware(),
            *fallback_middleware,
            SanitizeThinkingBlocksMiddleware(),
        ],
    )
