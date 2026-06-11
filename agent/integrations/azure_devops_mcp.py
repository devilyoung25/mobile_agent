"""Azure DevOps MCP tool loading with a read-only safety gate."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

DEFAULT_AZURE_DEVOPS_DOMAINS = "core,work,work-items,repositories,pipelines,test-plans,search,wiki"
_MCP_TIMEOUT_SECONDS = 30.0
_READ_ONLY_MARKERS = ("_list_", "_get_", "_search_", "_query_", "_show_")
_READ_ONLY_SUFFIXES = ("_my_work_items",)


def _organization() -> str:
    return os.environ.get("AZURE_DEVOPS_MCP_ORG", "").strip()


def _domains() -> list[str]:
    raw = os.environ.get("AZURE_DEVOPS_MCP_DOMAINS", DEFAULT_AZURE_DEVOPS_DOMAINS)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _transport() -> str:
    return os.environ.get("AZURE_DEVOPS_MCP_TRANSPORT", "streamable_http").strip().lower()


def is_azure_devops_read_only_tool(name: str) -> bool:
    """Return whether an Azure DevOps MCP tool is allowed in read-only phase."""
    normalized = name.strip().lower()
    if not normalized.startswith("mcp_ado_"):
        return False
    return any(marker in normalized for marker in _READ_ONLY_MARKERS) or normalized.endswith(
        _READ_ONLY_SUFFIXES
    )


def _filtered_read_only_tools(tools: list[BaseTool]) -> list[BaseTool]:
    allowed: list[BaseTool] = []
    blocked: list[str] = []
    for tool in tools:
        name = getattr(tool, "name", "")
        if isinstance(name, str) and is_azure_devops_read_only_tool(name):
            allowed.append(tool)
        elif isinstance(name, str) and name.startswith("mcp_ado_"):
            blocked.append(name)
    if blocked:
        logger.info("Blocked %d non-read-only Azure DevOps MCP tool(s)", len(blocked))
    return allowed


def _local_server_config(org: str) -> dict[str, Any]:
    package = os.environ.get("AZURE_DEVOPS_MCP_PACKAGE", "@azure-devops/mcp")
    args = ["-y", package, org]
    authentication = os.environ.get("AZURE_DEVOPS_MCP_AUTHENTICATION", "").strip()
    if authentication:
        args.extend(["--authentication", authentication])
    domains = _domains()
    if domains:
        args.append("-d")
        args.extend(domains)
    env: dict[str, str] = {}
    project = os.environ.get("AZURE_DEVOPS_MCP_PROJECT", "").strip()
    team = os.environ.get("AZURE_DEVOPS_MCP_TEAM", "").strip()
    if project:
        env["ado_mcp_project"] = project
    if team:
        env["ado_mcp_team"] = team
    config: dict[str, Any] = {
        "transport": "stdio",
        "command": os.environ.get("AZURE_DEVOPS_MCP_COMMAND", "npx"),
        "args": args,
    }
    if env:
        config["env"] = env
    return config


def _remote_server_config(org: str) -> dict[str, Any]:
    url = os.environ.get("AZURE_DEVOPS_MCP_URL", "").strip() or f"https://mcp.dev.azure.com/{org}"
    return {
        "transport": "streamable_http",
        "url": url,
        "timeout": timedelta(seconds=_MCP_TIMEOUT_SECONDS),
    }


def _server_config() -> dict[str, Any] | None:
    org = _organization()
    if not org:
        return None
    if _transport() == "stdio":
        return _local_server_config(org)
    return _remote_server_config(org)


async def _build_mcp_tools(config: dict[str, Any]) -> list[BaseTool]:
    def _make_client() -> Any:
        # Imported in a thread: the import chain (mcp -> jsonschema) does
        # blocking filesystem I/O that the ASGI event loop must not run.
        from langchain_mcp_adapters.client import MultiServerMCPClient

        return MultiServerMCPClient({"azure-devops": config})

    client = await asyncio.to_thread(_make_client)
    return await client.get_tools()


async def load_azure_devops_read_only_tools() -> list[BaseTool]:
    """Load read-only Azure DevOps MCP tools when an organization is configured."""
    config = _server_config()
    if config is None:
        logger.info("Azure DevOps MCP disabled: AZURE_DEVOPS_MCP_ORG is not configured")
        return []
    try:
        tools = await _build_mcp_tools(config)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load Azure DevOps MCP tools", exc_info=True)
        return []
    allowed = _filtered_read_only_tools(tools)
    logger.info("Loaded %d Azure DevOps MCP read-only tool(s)", len(allowed))
    return allowed
