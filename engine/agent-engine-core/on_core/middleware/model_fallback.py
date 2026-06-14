"""Generic model fallback middleware.

Provider routing belongs to ON Model Gateway. This middleware is intentionally
provider-agnostic and is only kept as a small compatibility hook when the
composition layer explicitly supplies a secondary gateway-backed model.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 413, 422}
_TRANSIENT_NAME_MARKERS = (
    "timeout",
    "rate",
    "connection",
    "temporar",
    "overload",
    "unavailable",
)


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _should_fallback(exc: BaseException) -> bool:
    if type(exc).__name__ == "StreamChunkTimeoutError":
        return True
    status = _status_code(exc)
    if status in _RETRYABLE_STATUS_CODES:
        return True
    if status in _NON_RETRYABLE_STATUS_CODES:
        return False
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return any(marker in name or marker in message for marker in _TRANSIENT_NAME_MARKERS)


def _error_body(exc: BaseException) -> dict[str, Any]:
    body = getattr(exc, "body", None)
    return body if isinstance(body, dict) else {}


def _nested_str(data: dict[str, Any], *keys: str) -> str | None:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) and current else None


def _model_access_error_message(exc: BaseException) -> str | None:
    status = _status_code(exc)
    body = _error_body(exc)
    code = _nested_str(body, "error", "code")
    if status in _NON_RETRYABLE_STATUS_CODES and code in {
        "model_not_found",
        "model_not_available",
        "context_length_exceeded",
    }:
        provider_message = _nested_str(body, "error", "message") or str(exc)
        return (
            "The selected gateway model is not available for this workspace. "
            f"Gateway returned: {provider_message}"
        )
    return None


class ModelFallbackMiddleware(AgentMiddleware):
    """Retry the model call against explicitly configured fallback models."""

    def __init__(self, fallback_model: BaseChatModel | Sequence[BaseChatModel]) -> None:
        super().__init__()
        if isinstance(fallback_model, Sequence):
            self._fallback_models = tuple(fallback_model)
        else:
            self._fallback_models = (fallback_model,)

    @staticmethod
    def _model_label(model: BaseChatModel) -> str:
        return str(
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or model.__class__.__name__
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        try:
            return handler(request)
        except Exception as exc:
            access_error_message = _model_access_error_message(exc)
            if access_error_message is not None:
                logger.warning("Model access error surfaced to user: %s", type(exc).__name__)
                return AIMessage(content=access_error_message)
            if not _should_fallback(exc):
                raise
            last_exc: BaseException = exc
            for fallback_model in self._fallback_models:
                logger.warning(
                    "Model failed (%s); falling back to %s",
                    type(last_exc).__name__,
                    self._model_label(fallback_model),
                )
                try:
                    return handler(request.override(model=fallback_model))
                except Exception as fallback_exc:
                    if not _should_fallback(fallback_exc):
                        raise
                    last_exc = fallback_exc
            raise last_exc from None

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        try:
            return await handler(request)
        except Exception as exc:
            access_error_message = _model_access_error_message(exc)
            if access_error_message is not None:
                logger.warning("Model access error surfaced to user: %s", type(exc).__name__)
                return AIMessage(content=access_error_message)
            if not _should_fallback(exc):
                raise
            last_exc: BaseException = exc
            for fallback_model in self._fallback_models:
                logger.warning(
                    "Model failed (%s); falling back to %s",
                    type(last_exc).__name__,
                    self._model_label(fallback_model),
                )
                try:
                    return await handler(request.override(model=fallback_model))
                except Exception as fallback_exc:
                    if not _should_fallback(fallback_exc):
                        raise
                    last_exc = fallback_exc
            raise last_exc from None
