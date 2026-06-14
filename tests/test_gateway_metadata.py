"""Tests for gateway capability discovery (model_launcher.gateway_metadata).

Network IO is mocked; the cache is reset between tests by the autouse fixture in
conftest. These lock in: extended /v1/models parsing, TTL caching, env fallback
when the gateway is unreachable, and that snapshot() never performs IO.
"""

from __future__ import annotations

import httpx
import pytest
from model_launcher import gateway_metadata


def _payload(models: list[dict[str, object]]) -> dict[str, object]:
    return {"object": "list", "data": models}


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    last_url: str | None = None
    last_headers: dict[str, str] | None = None

    def __init__(self, *, payload: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        type(self).last_url = url
        type(self).last_headers = headers
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload or _payload([]))


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict[str, object] | None = None,
    exc: Exception | None = None,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _FakeAsyncClient(payload=payload, exc=exc))


async def test_fetch_models_parses_extended_openai_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        payload=_payload(
            [
                {
                    "id": "on-auto-coder",
                    "object": "model",
                    "label": "ON Auto Coder",
                    "max_input_tokens": 200000,
                    "max_output_tokens": 64000,
                    "supports_images": False,
                    "efforts": ["medium", "high"],
                    "default_effort": "medium",
                }
            ]
        ),
    )

    models = await gateway_metadata.fetch_models()

    assert len(models) == 1
    model = models[0]
    assert model.id == "on-auto-coder"
    assert model.label == "ON Auto Coder"
    assert model.max_input_tokens == 200000
    assert model.max_output_tokens == 64000
    assert model.supports_images is False
    assert model.efforts == ("medium", "high")
    assert model.default_effort == "medium"
    assert _FakeAsyncClient.last_url is not None and _FakeAsyncClient.last_url.endswith("/models")
    assert _FakeAsyncClient.last_headers is not None
    assert _FakeAsyncClient.last_headers["Authorization"].startswith("Bearer ")


async def test_fetch_models_raises_on_empty_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, payload=_payload([]))
    with pytest.raises(ValueError):
        await gateway_metadata.fetch_models()


async def test_get_models_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def factory(**_kw: object) -> _FakeAsyncClient:
        calls["n"] += 1
        return _FakeAsyncClient(payload=_payload([{"id": "on-auto-coder", "object": "model"}]))

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setenv("MODEL_GATEWAY_METADATA_TTL", "120")

    first = await gateway_metadata.get_models()
    second = await gateway_metadata.get_models()

    assert [m.id for m in first] == ["on-auto-coder"]
    assert first == second
    assert calls["n"] == 1  # second call served from cache, no new fetch


async def test_get_models_falls_back_to_env_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, exc=httpx.ConnectError("boom"))
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "")

    models = await gateway_metadata.get_models()

    assert [m.id for m in models] == ["on-auto-coder"]  # env fallback, never raises


def test_snapshot_is_non_blocking_and_uses_env_when_cold(monkeypatch: pytest.MonkeyPatch) -> None:
    # snapshot() must not perform IO: break httpx so any network attempt would fail loudly.
    def _boom(**_kw: object) -> object:
        raise AssertionError("snapshot() must not perform network IO")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "on-extra")

    ids = [m.id for m in gateway_metadata.snapshot()]

    assert "on-auto-coder" in ids
    assert "on-extra" in ids


def test_env_fallback_reads_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "")
    monkeypatch.setenv("MODEL_GATEWAY_IMAGE_MODELS", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_EFFORTS", "medium,high")
    monkeypatch.setenv("MODEL_GATEWAY_MAX_INPUT_TOKENS", "128000")

    model = next(m for m in gateway_metadata.snapshot() if m.id == "on-auto-coder")

    assert model.supports_images is True
    assert model.efforts == ("medium", "high")
    assert model.max_input_tokens == 128000


def test_gateway_model_to_profile_includes_context_window() -> None:
    model = gateway_metadata.GatewayModel(
        id="on-auto-coder",
        label="ON Auto Coder",
        max_input_tokens=200000,
        max_output_tokens=64000,
        supports_images=True,
        efforts=("medium",),
        default_effort="medium",
    )
    profile = model.to_profile()
    assert profile is not None
    assert profile["max_input_tokens"] == 200000
    assert profile["image_inputs"] is True


def test_gateway_model_to_profile_omits_unknown_context_window() -> None:
    model = gateway_metadata.GatewayModel(
        id="on-auto-coder",
        label="ON Auto Coder",
        max_input_tokens=None,
        max_output_tokens=None,
        supports_images=False,
        efforts=("medium",),
        default_effort="medium",
    )
    profile = model.to_profile()
    assert profile is not None
    assert "max_input_tokens" not in profile
