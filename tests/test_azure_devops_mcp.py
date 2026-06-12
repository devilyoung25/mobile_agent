from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import integration_azure_devops as ado
import pytest
from mcp_toolset import McpToolsetProvider, ToolPolicy, filter_tools


def test_read_only_policy_allows_read_operations() -> None:
    allowed = [
        "mcp_ado_wit_get_work_item",
        "mcp_ado_repo_list_branches_by_repo",
        "mcp_ado_search_code",
        "mcp_ado_wit_query_by_wiql",
        "mcp_ado_wit_my_work_items",
        "wit_work_item",
        "repo_repository",
        "repo_pull_request",
        "pipelines_build",
        "search_workitem",
    ]

    assert all(ado.is_azure_devops_read_only_tool(name) for name in allowed)


def test_read_only_policy_blocks_persistent_operations() -> None:
    blocked = [
        "mcp_ado_repo_create_pull_request",
        "mcp_ado_wit_add_work_item_comment",
        "mcp_ado_repo_update_pull_request",
        "mcp_ado_pipelines_run_pipeline",
        "wit_work_item_write",
        "repo_create_branch",
        "pipelines_write",
        "other_server_tool",
    ]

    assert not any(ado.is_azure_devops_read_only_tool(name) for name in blocked)


def test_filter_tools_splits_allowed_and_blocked() -> None:
    read_tool = SimpleNamespace(name="mcp_ado_wit_get_work_item")
    write_tool = SimpleNamespace(name="mcp_ado_repo_create_pull_request")
    remote_read_tool = SimpleNamespace(name="wit_work_item")
    remote_write_tool = SimpleNamespace(name="wit_work_item_write")
    foreign_tool = SimpleNamespace(name="fetch_url")

    result = filter_tools(
        [read_tool, write_tool, remote_read_tool, remote_write_tool, foreign_tool],
        ado.READ_ONLY_POLICY,
    )

    assert result.allowed == [read_tool, remote_read_tool]
    assert result.blocked == ["mcp_ado_repo_create_pull_request"]


def test_policy_deny_markers_win_over_allow() -> None:
    policy = ToolPolicy(prefix="x_", allow_markers=("_get_",), deny_markers=("_get_secret",))
    assert policy.allows("x_repo_get_item") is True
    assert policy.allows("x_repo_get_secret") is False


def test_provider_none_without_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_MCP_ORG", raising=False)
    assert ado.azure_devops_provider() is None


@pytest.mark.asyncio
async def test_load_tools_skips_without_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_MCP_ORG", raising=False)
    assert await ado.load_azure_devops_read_only_tools() == []


@pytest.mark.asyncio
async def test_load_tools_filters_loaded_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")
    read_tool = SimpleNamespace(name="mcp_ado_wit_get_work_item")
    write_tool = SimpleNamespace(name="mcp_ado_wit_add_work_item_comment")

    with patch.object(
        McpToolsetProvider,
        "_build_tools",
        new_callable=AsyncMock,
        return_value=[read_tool, write_tool],
    ) as build:
        tools = await ado.load_azure_devops_read_only_tools()

    assert tools == [read_tool]
    build.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_tools_degrades_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")
    with patch.object(
        McpToolsetProvider,
        "_build_tools",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        assert await ado.load_azure_devops_read_only_tools() == []


def test_local_server_config_uses_official_package_and_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_DOMAINS", "core,work-items,repositories")
    monkeypatch.setenv("AZURE_DEVOPS_MCP_AUTHENTICATION", "azcli")
    monkeypatch.setenv("AZURE_DEVOPS_MCP_PROJECT", "Mobile")

    config = ado._local_server_config("onoff")

    assert config["transport"] == "stdio"
    assert config["command"] == "npx"
    assert config["args"] == [
        "-y",
        "@azure-devops/mcp",
        "onoff",
        "--authentication",
        "azcli",
        "-d",
        "core",
        "work-items",
        "repositories",
    ]
    assert config["env"] == {"ado_mcp_project": "Mobile"}


def test_remote_server_config_uses_official_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")
    monkeypatch.setenv("AZURE_DEVOPS_MCP_DOMAINS", "core,work-items,repositories,wiki")
    provider = ado.azure_devops_provider(bearer_token="token")
    assert provider is not None
    config = provider.server_config

    assert config["transport"] == "streamable_http"
    assert config["url"] == "https://mcp.dev.azure.com/onoff"
    assert config["headers"] == {
        "X-MCP-Readonly": "true",
        "X-MCP-Toolsets": "repos,wiki,wit",
        "Authorization": "Bearer token",
    }


def test_provider_carries_prompt_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")
    provider = ado.azure_devops_provider()
    assert provider is not None
    assert "Read-Only Context Phase" in provider.prompt_fragment
    assert "Do not use shell commands (`az`, `curl`, custom scripts)" in provider.prompt_fragment
    assert provider.policy is ado.READ_ONLY_POLICY
