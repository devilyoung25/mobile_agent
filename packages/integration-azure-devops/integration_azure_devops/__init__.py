"""Azure DevOps MCP preset: env-driven server config + read-only policy.

Wraps the official ``@azure-devops/mcp`` server as an :class:`McpToolsetProvider`.
Write operations (create PR, comment work item, run pipeline, …) are blocked by
policy until the platform's human-approval flow promotes them explicitly.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from mcp_toolset import McpToolsetProvider, ToolPolicy

DEFAULT_AZURE_DEVOPS_DOMAINS = "core,work,work-items,repositories,pipelines,test-plans,search,wiki"
REMOTE_TOOLSET_BY_DOMAIN = {
    "repositories": "repos",
    "repos": "repos",
    "work-items": "wit",
    "wit": "wit",
    "pipelines": "pipelines",
    "wiki": "wiki",
    "work": "work",
    "test-plans": "testplan",
    "testplan": "testplan",
}
# Marker-less read tools the allow_markers below can't catch: these start with
# ``search_`` (not ``_search_``), so they need an explicit allow entry. Every
# other read tool (``repo_list_*``, ``repo_get_*``, ``wit_get_*``,
# ``repo_search_commits``, ``pipelines_*_get_*`` …) is admitted by the markers.
REMOTE_READ_ONLY_TOOLS = (
    "search_code",
    "search_wiki",
    "search_workitem",
)

# Write verbs — defense-in-depth. Read-marker absence already blocks writes;
# these also reject any hypothetical hybrid name that pairs a read marker with a
# mutating verb (e.g. ``*_list_and_update_*``).
WRITE_DENY_MARKERS = (
    "_create_",
    "_update_",
    "_delete_",
    "_add_",
    "_remove_",
    "_run_",
    "_queue_",
    "_publish_",
    "_set_",
)

# No ``prefix``: this provider only ever connects to the Azure DevOps server, so
# every returned tool is an ADO tool. The official ``@azure-devops/mcp`` stdio
# server exposes tools by their raw, un-prefixed names (``repo_list_repos_by_project``,
# ``wit_get_work_item`` …); a non-empty prefix would short-circuit the markers
# and silently drop everything but a few exact-name matches.
READ_ONLY_POLICY = ToolPolicy(
    prefix="",
    allow_names=REMOTE_READ_ONLY_TOOLS,
    allow_markers=("_list_", "_get_", "_search_", "_query_", "_show_"),
    allow_suffixes=("_my_work_items",),
    deny_markers=WRITE_DENY_MARKERS,
)

AZURE_DEVOPS_PROMPT_FRAGMENT = """---

### Azure DevOps: Read-Only Context Phase

This run is connected to Azure DevOps in a **read-only** capacity. You can gather context — work items, comments, relations, repositories, branches, pull requests, pipelines, and builds — through the available Azure DevOps tools, but you must NOT perform any persistent or write action.

Use the Azure DevOps MCP tools for Azure DevOps context. Do not use shell commands (`az`, `curl`, custom scripts) or generic HTTP tools as an Azure DevOps fallback. If the Azure DevOps MCP tools are unavailable or fail, stop and report the MCP/configuration failure instead of trying another credential path.

**Discovering repositories:** To find the repositories in a project, call the repository-listing tool (`repo_list_repos_by_project`) for that project — this is the only authoritative source of repositories. Never use `search_code` to enumerate or guess repositories, and never infer a repository's existence from search results: `search_code` is only valid *after* you already know a real repository name. Do not treat `Fetch`/HTTP against `dev.azure.com` as a reliable way to read repositories (the web app is a session-protected SPA). If no repository-listing tool is available to you, say so explicitly rather than guessing a repository name.

Specifically, in this phase you must NEVER:
- Open, update, merge, or approve pull requests.
- Create or delete branches, or push commits to Azure DevOps.
- Comment on, close, or modify work items.
- Queue or cancel pipelines/builds.
- Change repository policies or permissions, or delete any resource.

Writes to Azure DevOps (creating a PR, commenting on a work item, relating a PR to a work item) are gated behind an explicit human approval step handled outside the agent; never assume that approval here.

When you have finished gathering context and reasoning about the task, produce a concise technical summary of your findings and proposed change, and stop. Do not claim that a PR, branch, comment, or pipeline run was created."""

_MCP_TIMEOUT_SECONDS = 30.0


def _organization() -> str:
    return os.environ.get("AZURE_DEVOPS_MCP_ORG", "").strip()


def _domains() -> list[str]:
    raw = os.environ.get("AZURE_DEVOPS_MCP_DOMAINS", DEFAULT_AZURE_DEVOPS_DOMAINS)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _remote_toolsets() -> str:
    toolsets = {
        REMOTE_TOOLSET_BY_DOMAIN[domain]
        for domain in _domains()
        if domain in REMOTE_TOOLSET_BY_DOMAIN
    }
    return ",".join(sorted(toolsets))


def _transport() -> str:
    return os.environ.get("AZURE_DEVOPS_MCP_TRANSPORT", "streamable_http").strip().lower()


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


def _remote_server_config(org: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    url = os.environ.get("AZURE_DEVOPS_MCP_URL", "").strip() or f"https://mcp.dev.azure.com/{org}"
    config: dict[str, Any] = {
        "transport": "streamable_http",
        "url": url,
        "timeout": timedelta(seconds=_MCP_TIMEOUT_SECONDS),
    }
    if headers:
        config["headers"] = headers
    return config


def _server_config(headers: dict[str, str] | None = None) -> dict[str, Any] | None:
    org = _organization()
    if not org:
        return None
    if _transport() == "stdio":
        return _local_server_config(org)
    return _remote_server_config(org, headers)


def azure_devops_provider(*, bearer_token: str | None = None) -> McpToolsetProvider | None:
    """The Azure DevOps read-only toolset, or ``None`` when not configured.

    ``bearer_token`` authenticates the remote (streamable_http) endpoint; the
    stdio transport authenticates via the local server's own flags instead.
    """
    headers = {"X-MCP-Readonly": "true"}
    toolsets = _remote_toolsets()
    if toolsets:
        headers["X-MCP-Toolsets"] = toolsets
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    config = _server_config(headers)
    if config is None:
        return None
    return McpToolsetProvider(
        name="azure-devops",
        server_config=config,
        policy=READ_ONLY_POLICY,
        prompt_fragment=AZURE_DEVOPS_PROMPT_FRAGMENT,
        timeout_seconds=_MCP_TIMEOUT_SECONDS,
    )


def is_azure_devops_read_only_tool(name: str) -> bool:
    """Back-compat helper: whether a tool name passes the read-only policy."""
    return READ_ONLY_POLICY.allows(name)


async def load_azure_devops_read_only_tools(*, bearer_token: str | None = None) -> list[Any]:
    """Load read-only Azure DevOps MCP tools when an organization is configured."""
    import logging

    provider = azure_devops_provider(bearer_token=bearer_token)
    if provider is None:
        logging.getLogger(__name__).info(
            "Azure DevOps MCP disabled: AZURE_DEVOPS_MCP_ORG is not configured"
        )
        return []
    return await provider.load_tools()
