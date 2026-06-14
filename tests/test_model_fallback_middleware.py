"""Tests for provider-agnostic ModelFallbackMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from on_core.middleware.model_fallback import (
    ModelFallbackMiddleware,
    _should_fallback,
)


class GatewayError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class GatewayTimeoutError(Exception):
    pass


def _make_request() -> MagicMock:
    request = MagicMock()
    request.override = MagicMock(return_value=MagicMock(name="overridden_request"))
    return request


class TestShouldFallback:
    def test_529_overload_falls_back(self) -> None:
        assert _should_fallback(GatewayError("Overloaded", status_code=529)) is True

    def test_503_falls_back(self) -> None:
        assert _should_fallback(GatewayError("unavailable", status_code=503)) is True

    def test_rate_limit_falls_back(self) -> None:
        assert _should_fallback(GatewayError("rate", status_code=429)) is True

    def test_timeout_name_falls_back(self) -> None:
        assert _should_fallback(GatewayTimeoutError("timeout")) is True

    def test_400_does_not_fall_back(self) -> None:
        assert _should_fallback(GatewayError("bad", status_code=400)) is False

    def test_value_error_does_not_fall_back(self) -> None:
        assert _should_fallback(ValueError("nope")) is False

    def test_stream_chunk_timeout_falls_back(self) -> None:
        class StreamChunkTimeoutError(Exception):
            pass

        assert _should_fallback(StreamChunkTimeoutError("stalled")) is True


class TestModelFallbackMiddleware:
    @pytest.mark.asyncio
    async def test_async_falls_over_on_overloaded(self) -> None:
        fallback_model = MagicMock(name="fallback_model")
        middleware = ModelFallbackMiddleware(fallback_model)

        calls: list[object] = []
        good_response = MagicMock(result=[AIMessage(content="ok from fallback")])

        async def handler(req: object) -> object:
            calls.append(req)
            if len(calls) == 1:
                raise GatewayError("Overloaded", status_code=529)
            return good_response

        request = _make_request()
        result = await middleware.awrap_model_call(request, handler)

        assert result is good_response
        assert len(calls) == 2
        request.override.assert_called_once_with(model=fallback_model)
        assert calls[1] is request.override.return_value

    @pytest.mark.asyncio
    async def test_async_propagates_non_transient_error(self) -> None:
        middleware = ModelFallbackMiddleware(MagicMock())
        calls: list[object] = []

        async def handler(req: object) -> object:
            calls.append(req)
            raise ValueError("not transient")

        with pytest.raises(ValueError, match="not transient"):
            await middleware.awrap_model_call(_make_request(), handler)

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_async_surfaces_model_unavailable_error(self) -> None:
        middleware = ModelFallbackMiddleware(MagicMock())

        async def handler(_req: object) -> object:
            raise GatewayError(
                "model unavailable",
                status_code=404,
                body={
                    "error": {
                        "code": "model_not_found",
                        "message": "No model named on-auto-coder",
                    }
                },
            )

        result = await middleware.awrap_model_call(_make_request(), handler)

        assert isinstance(result, AIMessage)
        assert "selected gateway model is not available" in result.text
        assert "No model named on-auto-coder" in result.text

    @pytest.mark.asyncio
    async def test_async_does_not_double_fall_back(self) -> None:
        middleware = ModelFallbackMiddleware(MagicMock())
        calls: list[object] = []

        async def handler(req: object) -> object:
            calls.append(req)
            raise GatewayError("unavailable", status_code=503)

        with pytest.raises(GatewayError):
            await middleware.awrap_model_call(_make_request(), handler)

        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_async_tries_multiple_fallbacks_in_order(self) -> None:
        fallback_1 = MagicMock(name="fallback_1")
        fallback_2 = MagicMock(name="fallback_2")
        middleware = ModelFallbackMiddleware([fallback_1, fallback_2])
        calls: list[object] = []
        good_response = MagicMock(result=[AIMessage(content="ok from second fallback")])

        async def handler(req: object) -> object:
            calls.append(req)
            if len(calls) <= 2:
                raise GatewayError("unavailable", status_code=503)
            return good_response

        request = _make_request()
        override_1 = MagicMock(name="override_1")
        override_2 = MagicMock(name="override_2")
        request.override.side_effect = [override_1, override_2]

        result = await middleware.awrap_model_call(request, handler)

        assert result is good_response
        assert calls == [request, override_1, override_2]
        assert request.override.call_args_list[0].kwargs == {"model": fallback_1}
        assert request.override.call_args_list[1].kwargs == {"model": fallback_2}

    def test_sync_falls_over_on_overloaded(self) -> None:
        fallback_model = MagicMock(name="fallback_model")
        middleware = ModelFallbackMiddleware(fallback_model)
        calls: list[object] = []
        good_response = MagicMock(result=[AIMessage(content="ok")])

        def handler(req: object) -> object:
            calls.append(req)
            if len(calls) == 1:
                raise GatewayError("Overloaded", status_code=529)
            return good_response

        request = _make_request()
        result = middleware.wrap_model_call(request, handler)

        assert result is good_response
        assert len(calls) == 2
        request.override.assert_called_once_with(model=fallback_model)
