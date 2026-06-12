"""Read-only Azure DevOps REST client for the dashboard.

Mints the signed-in user's Azure DevOps access token (the same Entra→ADO flow
the agent's MCP uses) and calls the Azure DevOps REST API directly, so the
dashboard can show live projects, repositories, pull requests, etc. without
spinning up an agent run. The token is minted server-side and never reaches the
frontend; only GET (and read-only WIQL) calls are issued.

Docs: https://learn.microsoft.com/en-us/rest/api/azure/devops/
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from identity_entra.tokens import get_azure_devops_access_token

logger = logging.getLogger(__name__)

API_VERSION = "7.1"
_TIMEOUT = httpx.Timeout(15.0)


def _organization() -> str:
    org = os.environ.get("AZURE_DEVOPS_MCP_ORG", "").strip()
    if not org:
        raise HTTPException(503, "azure_devops_not_configured")
    return org


def _base_url() -> str:
    return f"https://dev.azure.com/{_organization()}"


async def _ado_get(actor_id: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET an Azure DevOps REST resource as the signed-in user.

    Raises 403 when the user has no Azure DevOps token (not consented / not
    linked) and 502 for upstream failures. Azure DevOps answers an
    unauthenticated request with a 203 redirect to the sign-in page rather than
    a 401, so treat any non-JSON / redirect as an auth failure too.
    """
    token = await get_azure_devops_access_token(actor_id)
    if not token:
        raise HTTPException(403, "azure_devops_not_authorized")

    url = f"{_base_url()}{path}"
    request_params = {**(params or {}), "api-version": API_VERSION}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                url,
                params=request_params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Azure DevOps request failed: %s %s", path, exc)
        raise HTTPException(502, "azure_devops_unreachable") from exc

    if response.status_code in (401, 203, 302):
        raise HTTPException(403, "azure_devops_not_authorized")
    if response.status_code >= 400:
        logger.warning("Azure DevOps %s -> %s: %s", path, response.status_code, response.text[:300])
        raise HTTPException(502, "azure_devops_error")
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(403, "azure_devops_not_authorized") from exc
    return data if isinstance(data, dict) else {}


async def _ado_post(
    actor_id: str,
    path: str,
    body: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a read-only Azure DevOps query resource as the signed-in user."""
    token = await get_azure_devops_access_token(actor_id)
    if not token:
        raise HTTPException(403, "azure_devops_not_authorized")

    url = f"{_base_url()}{path}"
    request_params = {**(params or {}), "api-version": API_VERSION}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                url,
                params=request_params,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Azure DevOps request failed: %s %s", path, exc)
        raise HTTPException(502, "azure_devops_unreachable") from exc

    if response.status_code in (401, 203, 302):
        raise HTTPException(403, "azure_devops_not_authorized")
    if response.status_code >= 400:
        logger.warning("Azure DevOps %s -> %s: %s", path, response.status_code, response.text[:300])
        raise HTTPException(502, "azure_devops_error")
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(403, "azure_devops_not_authorized") from exc
    return data if isinstance(data, dict) else {}


def _project_path(project: str) -> str:
    return quote(project, safe="")


def _short_branch(ref: str | None) -> str | None:
    if isinstance(ref, str) and ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    return ref


async def list_projects(actor_id: str) -> list[dict[str, Any]]:
    """All projects the user can see in the organization."""
    data = await _ado_get(actor_id, "/_apis/projects", {"$top": 200})
    projects = data.get("value") if isinstance(data.get("value"), list) else []
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description"),
            "state": p.get("state"),
            "url": p.get("url"),
            "last_update_time": p.get("lastUpdateTime"),
        }
        for p in projects
        if isinstance(p, dict)
    ]


async def list_repositories(actor_id: str, project: str | None = None) -> list[dict[str, Any]]:
    """Repositories across the org, or scoped to a single project.

    Each repo carries a ``full_name`` of ``"<project>/<repo>"`` — the Azure
    DevOps analogue of GitHub's ``owner/repo`` — which the RepoSelector keys on.
    """
    path = (
        f"/{_project_path(project)}/_apis/git/repositories"
        if project and project.strip()
        else "/_apis/git/repositories"
    )
    data = await _ado_get(actor_id, path)
    repos = data.get("value") if isinstance(data.get("value"), list) else []
    result: list[dict[str, Any]] = []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        proj = repo.get("project") if isinstance(repo.get("project"), dict) else {}
        project_name = proj.get("name") or ""
        name = repo.get("name") or ""
        result.append(
            {
                "full_name": f"{project_name}/{name}" if project_name else name,
                "project": project_name,
                "name": name,
                "id": repo.get("id"),
                "default_branch": _short_branch(repo.get("defaultBranch")),
                "web_url": repo.get("webUrl"),
                "size": repo.get("size"),
                "is_disabled": repo.get("isDisabled", False),
            }
        )
    result.sort(key=lambda r: r["full_name"].lower())
    return result


async def list_pull_requests(
    actor_id: str,
    project: str,
    *,
    status: str = "active",
    top: int = 50,
) -> list[dict[str, Any]]:
    """Open (or completed/abandoned) pull requests for a single project."""
    if not project or not project.strip():
        raise HTTPException(400, "project_required")
    path = f"/{_project_path(project)}/_apis/git/pullrequests"
    data = await _ado_get(
        actor_id, path, {"searchCriteria.status": status, "$top": top}
    )
    prs = data.get("value") if isinstance(data.get("value"), list) else []
    result: list[dict[str, Any]] = []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        repo = pr.get("repository") if isinstance(pr.get("repository"), dict) else {}
        created_by = pr.get("createdBy") if isinstance(pr.get("createdBy"), dict) else {}
        pr_id = pr.get("pullRequestId")
        repo_web = repo.get("webUrl")
        web_url = f"{repo_web}/pullrequest/{pr_id}" if repo_web and pr_id else None
        result.append(
            {
                "id": pr_id,
                "title": pr.get("title"),
                "status": pr.get("status"),
                "is_draft": pr.get("isDraft", False),
                "author": created_by.get("displayName"),
                "author_email": created_by.get("uniqueName"),
                "created_date": pr.get("creationDate"),
                "source_branch": _short_branch(pr.get("sourceRefName")),
                "target_branch": _short_branch(pr.get("targetRefName")),
                "repo": repo.get("name"),
                "project": project,
                "web_url": web_url,
            }
        )
    return result


def _wiql_project(value: str) -> str:
    return value.replace("'", "''")


def _period_filter(period: str) -> str:
    if period == "7d":
        return " AND [System.ChangedDate] >= @Today - 7"
    if period == "30d":
        return " AND [System.ChangedDate] >= @Today - 30"
    return ""


async def list_work_item_state_counts(
    actor_id: str,
    project: str,
    *,
    period: str = "30d",
    top: int = 500,
) -> dict[str, Any]:
    """Count recent work items by state using WIQL plus a read-only batch fetch."""
    if not project or not project.strip():
        raise HTTPException(400, "project_required")

    query = (
        "SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.TeamProject] = '{_wiql_project(project)}'"
        f"{_period_filter(period)} "
        "ORDER BY [System.ChangedDate] DESC"
    )
    wiql = await _ado_post(
        actor_id,
        f"/{_project_path(project)}/_apis/wit/wiql",
        {"query": query},
        {"$top": top},
    )
    ids = [
        item.get("id")
        for item in wiql.get("workItems", [])
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    ]
    counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    if not ids:
        return {"total": 0, "states": [], "types": [], "limited": False}

    for start in range(0, len(ids), 200):
        batch = await _ado_post(
            actor_id,
            f"/{_project_path(project)}/_apis/wit/workitemsbatch",
            {
                "ids": ids[start : start + 200],
                "fields": [
                    "System.State",
                    "System.WorkItemType",
                ],
            },
        )
        for item in batch.get("value", []):
            if not isinstance(item, dict):
                continue
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            state = str(fields.get("System.State") or "Sin estado")
            work_type = str(fields.get("System.WorkItemType") or "Sin tipo")
            counts[state] = counts.get(state, 0) + 1
            type_counts[work_type] = type_counts.get(work_type, 0) + 1

    return {
        "total": len(ids),
        "states": [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "types": [
            {"name": name, "count": count}
            for name, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "limited": len(ids) >= top,
    }


async def list_recent_builds(
    actor_id: str,
    project: str,
    *,
    top: int = 10,
) -> list[dict[str, Any]]:
    """Recent builds for a single Azure DevOps project."""
    if not project or not project.strip():
        raise HTTPException(400, "project_required")
    data = await _ado_get(
        actor_id,
        f"/{_project_path(project)}/_apis/build/builds",
        {"$top": top, "queryOrder": "finishTimeDescending"},
    )
    builds = data.get("value") if isinstance(data.get("value"), list) else []
    result: list[dict[str, Any]] = []
    for build in builds:
        if not isinstance(build, dict):
            continue
        definition = build.get("definition") if isinstance(build.get("definition"), dict) else {}
        requested_for = build.get("requestedFor") if isinstance(build.get("requestedFor"), dict) else {}
        links = build.get("_links") if isinstance(build.get("_links"), dict) else {}
        web = links.get("web") if isinstance(links.get("web"), dict) else {}
        result.append(
            {
                "id": build.get("id"),
                "build_number": build.get("buildNumber"),
                "definition": definition.get("name"),
                "status": build.get("status"),
                "result": build.get("result"),
                "source_branch": _short_branch(build.get("sourceBranch")),
                "requested_for": requested_for.get("displayName"),
                "queue_time": build.get("queueTime"),
                "start_time": build.get("startTime"),
                "finish_time": build.get("finishTime"),
                "web_url": web.get("href"),
            }
        )
    return result


async def get_project_usage(actor_id: str, project: str, *, period: str = "30d") -> dict[str, Any]:
    """Small Azure DevOps activity snapshot for the dashboard usage page."""
    work_items = await list_work_item_state_counts(actor_id, project, period=period)
    builds = await list_recent_builds(actor_id, project)
    return {
        "project": project,
        "period": period,
        "work_items": work_items,
        "recent_builds": builds,
    }
