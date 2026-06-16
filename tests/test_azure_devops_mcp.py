from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import integration_azure_devops as ado
import pytest
from capability_gateway import McpToolsetProvider, ToolPolicy, filter_tools


def test_read_only_policy_allows_read_operations() -> None:
    # Raw, un-prefixed names as the official @azure-devops/mcp stdio server emits.
    allowed = [
        "repo_list_repos_by_project",
        "repo_list_branches_by_repo",
        "repo_get_repo_by_name_or_id",
        "wit_get_work_item",
        "wit_query_by_wiql",
        "wit_my_work_items",
        "search_code",
        "search_wiki",
        "search_workitem",
        "core_list_projects",
    ]

    assert all(ado.is_azure_devops_read_only_tool(name) for name in allowed)


def test_read_only_policy_blocks_persistent_operations() -> None:
    blocked = [
        "repo_create_pull_request",
        "wit_add_work_item_comment",
        "repo_update_pull_request",
        "pipelines_run_pipeline",
        "repo_create_branch",
        "wit_delete_work_item",
    ]

    assert not any(ado.is_azure_devops_read_only_tool(name) for name in blocked)


def test_filter_tools_splits_allowed_and_blocked() -> None:
    read_tool = SimpleNamespace(name="wit_get_work_item")
    list_tool = SimpleNamespace(name="repo_list_repos_by_project")
    write_tool = SimpleNamespace(name="repo_create_pull_request")
    comment_tool = SimpleNamespace(name="wit_add_work_item_comment")

    result = filter_tools(
        [read_tool, list_tool, write_tool, comment_tool],
        ado.READ_ONLY_POLICY,
    )

    assert result.allowed == [read_tool, list_tool]
    # prefix="" — every non-allowed tool now surfaces in the blocked list.
    assert result.blocked == ["repo_create_pull_request", "wit_add_work_item_comment"]


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
    assert "repo_list_repos_by_project" in provider.prompt_fragment
    assert "Never use `search_code` to enumerate" in provider.prompt_fragment
    assert provider.policy is ado.READ_ONLY_POLICY
