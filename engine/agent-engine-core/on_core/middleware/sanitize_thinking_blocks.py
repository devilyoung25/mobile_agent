"""Middleware that removes malformed (empty) thinking blocks before model calls.

Provider-neutral: it drops empty ``{"type": "thinking"}`` blocks from assistant
message content regardless of the model. This is a no-op for providers that never
emit such blocks (e.g. OpenAI-style string content), so the engine stays neutral —
it no longer needs to know which provider is behind the model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage


def _sanitize_messages(messages: list[Any]) -> None:
    for message in messages:
        if not isinstance(message, AIMessage) or not isinstance(message.content, list):
            continue
        content = [
            block
            for block in message.content
            if not (
                isinstance(block, dict)
                and block.get("type") == "thinking"
                and not block.get("thinking")
            )
        ]
        if len(content) != len(message.content):
            message.content = content


class SanitizeThinkingBlocksMiddleware(AgentMiddleware):
    """Drop empty thinking blocks before provider validation (provider-neutral)."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        _sanitize_messages(request.messages)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        _sanitize_messages(request.messages)
        return await handler(request)
