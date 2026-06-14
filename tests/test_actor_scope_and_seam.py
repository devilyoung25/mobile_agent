"""Tests for the A/B seam: actor scope resolution + the ToolLoader contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent.integrations.azure_devops_mcp import resolve_actor_scope
from mcp_toolset import ToolLoader, load_tools_for


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, payload: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    async def get(self, url: str, params: object = None, headers: object = None) -> _FakeResponse:
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._payload or {})


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, *, payload=None, exc=None) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _FakeAsyncClient(payload=payload, exc=exc))


async def test_resolve_actor_scope_returns_empty_without_actor() -> None:
    assert await resolve_actor_scope(None) == []
    assert await resolve_actor_scope("") == []


async def test_resolve_actor_scope_returns_empty_without_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_MCP_ORG", raising=False)
    assert await resolve_actor_scope("entra:user-oid") == []


async def test_resolve_actor_scope_returns_empty_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff-solution")
    with patch(
        "identity_entra.tokens.get_azure_devops_access_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await resolve_actor_scope("entra:user-oid") == []


async def test_resolve_actor_scope_lists_project_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff-solution")
    _patch_httpx(
        monkeypatch,
        payload={
            "value": [
                {"name": "AppMovil"},
                {"name": "Pagos"},
                {"id": "no-name"},
                {"name": "  "},
            ]
        },
    )
    with patch(
        "identity_entra.tokens.get_azure_devops_access_token",
        new_callable=AsyncMock,
        return_value="bearer-tok",
    ):
        scope = await resolve_actor_scope("entra:user-oid")

    assert scope == ["AppMovil", "Pagos"]  # sorted, blanks/nameless dropped


async def test_resolve_actor_scope_is_fail_soft_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff-solution")
    _patch_httpx(monkeypatch, exc=httpx.ConnectError("boom"))
    with patch(
        "identity_entra.tokens.get_azure_devops_access_token",
        new_callable=AsyncMock,
        return_value="bearer-tok",
    ):
        assert await resolve_actor_scope("entra:user-oid") == []


def test_tool_loader_protocol_accepts_conforming_callable() -> None:
    async def loader(actor_id, *, domain_pack, project_scope):  # noqa: ANN001, ANN202, ARG001
        return []

    assert isinstance(loader, ToolLoader)
    assert isinstance(load_tools_for, ToolLoader)
    assert not isinstance(object(), ToolLoader)
