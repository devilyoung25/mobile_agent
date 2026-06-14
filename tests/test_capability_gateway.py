from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool
from mcp_toolset import (
    CapabilityAdapter,
    CapabilityContext,
    CapabilityCredential,
    CapabilityDescriptor,
    CapabilityImplementation,
    CapabilityPolicy,
    ResolvedCredential,
    ToolPolicy,
    load_tools_for,
)
from mcp_toolset.adapters import RestAdapter
from mcp_toolset.gateway import _ADAPTERS, _load_capability_tools


def _tool(name: str) -> StructuredTool:
    def _run(project: str = "") -> str:
        return f"{name}:{project}"

    async def _arun(project: str = "") -> str:
        return f"{name}:{project}"

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=name,
        description=f"{name} test tool",
    )


class _FakeProvider:
    timeout_seconds = 1.0

    async def load_tools(self):
        return [
            _tool("repo_list_repos_by_project"),
            _tool("repo_create_pull_request"),
        ]


class _SlowProvider:
    timeout_seconds = 0.01

    async def load_tools(self):
        await asyncio.sleep(1)
        return [_tool("repo_list_repos_by_project")]


def test_capability_descriptor_validates_required_shape() -> None:
    with pytest.raises(ValueError, match="name is required"):
        CapabilityDescriptor(
            name="",
            description="desc",
            input_schema=None,
            output_schema=None,
            implementation=CapabilityImplementation(kind="mcp"),
        )

    with pytest.raises(ValueError, match="input_schema"):
        CapabilityDescriptor(
            name="bad.schema",
            description="desc",
            input_schema=[],  # type: ignore[arg-type]
            output_schema=None,
            implementation=CapabilityImplementation(kind="mcp"),
        )


async def test_unknown_domain_pack_returns_no_tools() -> None:
    assert await load_tools_for("entra:actor", domain_pack="unknown", project_scope=[]) == []


async def test_mobile_pack_loads_azure_devops_read_tools_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        "mcp_toolset.gateway._mint_azure_devops_bearer",
        AsyncMock(return_value="secret-token"),
    )

    def fake_provider(credential: ResolvedCredential) -> _FakeProvider:
        assert credential.kind == "azure_devops_bearer"
        assert credential.value == "secret-token"
        return _FakeProvider()

    monkeypatch.setattr("mcp_toolset.adapters._azure_devops_provider", fake_provider)

    tools = await load_tools_for(
        "entra:actor",
        domain_pack="mobile",
        project_scope=["TryController 2.0"],
    )

    assert [tool.name for tool in tools] == ["repo_list_repos_by_project"]
    assert tools[0].metadata["capability"] == {
        "name": "azure_devops.read",
        "requires_approval": False,
        "provenance_tags": ["azure-devops", "read-only", "mobile"],
        "implementation_kind": "mcp",
    }
    assert "secret-token" not in caplog.text
    assert "capability_gateway_event" in caplog.text


async def test_mobile_pack_without_actor_token_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(
        "mcp_toolset.gateway._mint_azure_devops_bearer",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("mcp_toolset.adapters._azure_devops_provider", provider)

    assert await load_tools_for("entra:actor", domain_pack="mobile", project_scope=[]) == []
    provider.assert_not_called()


async def test_capability_policy_deny_skips_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AsyncMock()
    monkeypatch.setitem(_ADAPTERS, "mcp", adapter)
    descriptor = CapabilityDescriptor(
        name="denied.capability",
        description="Denied capability",
        input_schema=None,
        output_schema=None,
        implementation=CapabilityImplementation(kind="mcp"),
        policy=CapabilityPolicy(mode="deny"),
    )
    context = CapabilityContext(
        actor_id="entra:actor",
        domain_pack="mobile",
        project_scope=(),
    )

    assert await _load_capability_tools(descriptor, context) == []
    adapter.load_tools.assert_not_called()


async def test_capability_timeout_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcp_toolset.gateway._mint_azure_devops_bearer",
        AsyncMock(return_value="secret-token"),
    )
    monkeypatch.setattr(
        "mcp_toolset.adapters._azure_devops_provider",
        lambda _credential: _SlowProvider(),
    )

    assert await load_tools_for("entra:actor", domain_pack="mobile", project_scope=[]) == []


async def test_rest_adapter_scaffold_satisfies_protocol_and_returns_empty() -> None:
    adapter = RestAdapter()
    assert isinstance(adapter, CapabilityAdapter)
    descriptor = CapabilityDescriptor(
        name="internal.rest.placeholder",
        description="Internal REST placeholder",
        input_schema=None,
        output_schema=None,
        implementation=CapabilityImplementation(kind="rest"),
        credential=CapabilityCredential(kind="none"),
    )
    tools = await adapter.load_tools(
        descriptor,
        ResolvedCredential(kind="none"),
        CapabilityContext(actor_id=None, domain_pack="mobile", project_scope=()),
    )
    assert tools == []


async def test_requires_approval_metadata_is_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = CapabilityDescriptor(
        name="future.write",
        description="Future write capability",
        input_schema=None,
        output_schema=None,
        implementation=CapabilityImplementation(kind="mcp"),
        policy=CapabilityPolicy(
            mode="requires_approval",
            tool_policy=ToolPolicy(allow_names=("future_write_tool",)),
        ),
    )
    context = CapabilityContext(
        actor_id=None,
        domain_pack="mobile",
        project_scope=(),
    )

    class _Adapter:
        async def load_tools(self, *_args):
            return [_tool("future_write_tool")]

    monkeypatch.setitem(_ADAPTERS, "mcp", _Adapter())
    tools = await _load_capability_tools(descriptor, context)

    assert tools[0].metadata["capability"]["requires_approval"] is True
