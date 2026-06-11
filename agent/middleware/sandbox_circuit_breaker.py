"""Circuit breaker for repeated unrecoverable sandbox failures."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

SANDBOX_CIRCUIT_BREAKER_THRESHOLD = 2
SANDBOX_UNRECOVERABLE_MESSAGE = "Sandbox became unrecoverable mid-task. Please retrigger."

_CIRCUIT_BREAKER_MARKER = "Sandbox circuit breaker triggered"
_SANDBOX_RECREATED_AFTER_CLIENT_ERROR = "sandbox_recreated_after_client_error"
_SANDBOX_ID_RE = re.compile(r"\bsb-[A-Za-z0-9-]+\b")


@dataclass(frozen=True)
class SandboxErrorStreak:
    reason: Literal["client_error", "recreated"]
    sandbox_id: str | None
    count: int


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, Mapping):
            text = block.get("text", "")
            parts.append(text if isinstance(text, str) else str(text))
        else:
            parts.append(str(block))
    return " ".join(parts)


def _extract_sandbox_id(text: str) -> str | None:
    match = _SANDBOX_ID_RE.search(text)
    return match.group(0) if match else None


def _last_message_has_circuit_breaker_marker(messages: Sequence[BaseMessage]) -> bool:
    if not messages:
        return False
    content = _content_to_text(getattr(messages[-1], "content", "") or "")
    return _CIRCUIT_BREAKER_MARKER in content


def _sandbox_error_streak(messages: Sequence[BaseMessage]) -> SandboxErrorStreak | None:
    sandbox_id: str | None = None
    reason: Literal["client_error", "recreated"] | None = None
    count = 0

    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            text = _content_to_text(message.content)
            if _SANDBOX_RECREATED_AFTER_CLIENT_ERROR in text:
                if reason is None:
                    reason = "recreated"
                elif reason != "recreated":
                    break
                count += 1
                continue

            message_sandbox_id = _extract_sandbox_id(text)
            if "SandboxClientError" not in text or message_sandbox_id is None:
                break
            if reason is None:
                reason = "client_error"
                sandbox_id = message_sandbox_id
            elif reason != "client_error" or message_sandbox_id != sandbox_id:
                break
            count += 1
            continue

        text = _content_to_text(getattr(message, "content", "") or "")
        if _CIRCUIT_BREAKER_MARKER in text:
            return None
        if getattr(message, "type", "") in {"human", "system"}:
            break

    if reason is None:
        return None
    return SandboxErrorStreak(reason=reason, sandbox_id=sandbox_id, count=count)


class SandboxCircuitBreakerMiddleware(AgentMiddleware[AgentState, Any]):
    """Stop runs that repeatedly hit the same dead sandbox."""

    state_schema = AgentState

    def __init__(self, *, threshold: int = SANDBOX_CIRCUIT_BREAKER_THRESHOLD) -> None:
        self.threshold = threshold

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:  # noqa: ARG002
        messages = state.get("messages", [])
        if _last_message_has_circuit_breaker_marker(messages):
            return None

        streak = _sandbox_error_streak(messages)
        if streak is None or streak.count <= self.threshold:
            return None

        if streak.reason == "recreated":
            detail = (
                f"{streak.count} consecutive sandbox recreations did not recover tool execution"
            )
        else:
            detail = f"{streak.count} consecutive sandbox tool failures against {streak.sandbox_id}"
        content = f"{_CIRCUIT_BREAKER_MARKER}: {detail}. {SANDBOX_UNRECOVERABLE_MESSAGE}"
        return {"jump_to": "end", "messages": [AIMessage(content=content)]}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        return self.before_model(state, runtime)
