from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.integrations import azure_devops_mcp


def test_is_azure_devops_read_only_tool_allows_read_operations() -> None:
    allowed = [
        "mcp_ado_wit_get_work_item",
        "mcp_ado_repo_list_branches_by_repo",
        "mcp_ado_search_code",
        "mcp_ado_wit_query_by_wiql",
        "mcp_ado_wit_my_work_items",
    ]

    assert all(azure_devops_mcp.is_azure_devops_read_only_tool(name) for name in allowed)


def test_is_azure_devops_read_only_tool_blocks_persistent_operations() -> None:
    blocked = [
        "mcp_ado_repo_create_pull_request",
        "mcp_ado_wit_add_work_item_comment",
        "mcp_ado_repo_update_pull_request",
        "mcp_ado_pipelines_run_pipeline",
        "github_foo",
    ]

    assert not any(azure_devops_mcp.is_azure_devops_read_only_tool(name) for name in blocked)


def test_filtered_read_only_tools_drops_write_tools() -> None:
    read_tool = SimpleNamespace(name="mcp_ado_wit_get_work_item")
    write_tool = SimpleNamespace(name="mcp_ado_repo_create_pull_request")
    other_tool = SimpleNamespace(name="slack_thread_reply")

    assert azure_devops_mcp._filtered_read_only_tools([read_tool, write_tool, other_tool]) == [
        read_tool
    ]


@pytest.mark.asyncio
async def test_load_azure_devops_tools_skips_non_entra_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")

    with patch.object(azure_devops_mcp, "_build_mcp_tools", new_callable=AsyncMock) as build:
        tools = await azure_devops_mcp.load_azure_devops_read_only_tools(auth_provider="github")

    assert tools == []
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_azure_devops_tools_skips_without_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_MCP_ORG", raising=False)

    with patch.object(azure_devops_mcp, "_build_mcp_tools", new_callable=AsyncMock) as build:
        tools = await azure_devops_mcp.load_azure_devops_read_only_tools(auth_provider="entra")

    assert tools == []
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_azure_devops_tools_filters_loaded_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff")
    read_tool = SimpleNamespace(name="mcp_ado_wit_get_work_item")
    write_tool = SimpleNamespace(name="mcp_ado_wit_add_work_item_comment")

    with patch.object(
        azure_devops_mcp,
        "_build_mcp_tools",
        new_callable=AsyncMock,
        return_value=[read_tool, write_tool],
    ) as build:
        tools = await azure_devops_mcp.load_azure_devops_read_only_tools(auth_provider="entra")

    assert tools == [read_tool]
    build.assert_awaited_once()


def test_local_server_config_uses_official_package_and_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_DOMAINS", "core,work-items,repositories")
    monkeypatch.setenv("AZURE_DEVOPS_MCP_AUTHENTICATION", "azcli")
    monkeypatch.setenv("AZURE_DEVOPS_MCP_PROJECT", "Mobile")

    config = azure_devops_mcp._local_server_config("onoff")

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


def test_remote_server_config_uses_official_remote_endpoint() -> None:
    config = azure_devops_mcp._remote_server_config("onoff")

    assert config["transport"] == "streamable_http"
    assert config["url"] == "https://mcp.dev.azure.com/onoff"
