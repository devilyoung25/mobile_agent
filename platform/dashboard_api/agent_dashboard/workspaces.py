"""Local workspace registry for dashboard-driven development runs.

This is deliberately small: it records local Git working copies selected by
the signed-in user. Azure DevOps remains the remote source of truth; a
workspace is only the local filesystem capability that lets the agent inspect,
diff, build, and test code without cloning into the ON Mobile Agent repo.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from langgraph_sdk import get_client
from pydantic import BaseModel

WORKSPACES_NAMESPACE_PREFIX = "workspaces"
DEFAULT_WORKTREE_ROOT = "~/.on-mobile-agent/worktrees"


class WorkspaceCreate(BaseModel):
    path: str
    label: str | None = None
    azure_project: str | None = None
    azure_repo: str | None = None


def _client():
    return get_client()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _namespace(actor_id: str) -> list[str]:
    return [WORKSPACES_NAMESPACE_PREFIX, actor_id]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _picker_enabled() -> bool:
    configured = os.environ.get("WORKSPACE_DIRECTORY_PICKER_ENABLED")
    if configured is not None:
        return _truthy(configured)

    api_base = os.environ.get("DASHBOARD_API_BASE_URL", "")
    return (
        "localhost" in api_base
        or "127.0.0.1" in api_base
        or os.environ.get("SANDBOX_TYPE") == "local"
    )


def _safe_remote_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.scheme or not parsed.netloc:
        return url
    host = parsed.hostname or parsed.netloc
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def _is_azure_devops_remote(url: str | None) -> bool:
    normalized = (url or "").strip()
    if not normalized:
        return False
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"dev.azure.com", "ssh.dev.azure.com"} or host.endswith(
        ".visualstudio.com"
    )


def _azure_devops_org_from_remote(url: str | None) -> str | None:
    normalized = (url or "").strip()
    if not normalized:
        return None
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host == "dev.azure.com":
        parts = [part for part in parsed.path.split("/") if part]
        return parts[0].lower() if parts else None
    if host == "ssh.dev.azure.com":
        parts = [part for part in parsed.path.split("/") if part]
        return parts[1].lower() if len(parts) >= 2 and parts[0].lower() == "v3" else None
    if host.endswith(".visualstudio.com"):
        return host.removesuffix(".visualstudio.com").lower() or None
    return None


def _configured_azure_devops_org() -> str | None:
    configured = os.environ.get("AZURE_DEVOPS_MCP_ORG", "").strip()
    if not configured:
        return None
    # The rest of the app expects an organization slug, but accepting a URL here
    # makes local env mistakes fail closed instead of silently bypassing the check.
    return (_azure_devops_org_from_remote(configured) or configured).strip().lower() or None


def _validate_azure_devops_remote(url: str | None) -> None:
    if not _is_azure_devops_remote(url):
        raise HTTPException(422, "workspace_path_not_azure_repo")
    configured_org = _configured_azure_devops_org()
    if not configured_org:
        return
    remote_org = _azure_devops_org_from_remote(url)
    if remote_org != configured_org:
        raise HTTPException(422, "workspace_path_wrong_azure_org")


def _allow_dirty_workspace() -> bool:
    return _truthy(os.environ.get("ON_MOBILE_AGENT_ALLOW_DIRTY_WORKSPACE"))


def _run_git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise HTTPException(422, f"workspace_git_error: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _run_git_status(path: Path, *args: str) -> int:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    ).returncode


def _worktree_root() -> Path:
    configured = os.environ.get("ON_MOBILE_AGENT_WORKTREE_ROOT") or DEFAULT_WORKTREE_ROOT
    return Path(configured).expanduser().resolve()


def _worktree_branch(thread_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", thread_id).strip("-")
    prefix = (safe or "run")[:24].strip("-") or "run"
    digest = hashlib.sha256(thread_id.encode()).hexdigest()[:8]
    return f"on-mobile-agent/{prefix}-{digest}"


def _worktree_path(workspace_id: str, thread_id: str) -> Path:
    return _worktree_root() / _slug(workspace_id) / _slug(thread_id)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def _workspace_id(actor_id: str, root: Path, label: str) -> str:
    digest = hashlib.sha256(f"{actor_id}:{root}".encode()).hexdigest()[:10]
    return f"{_slug(label)}-{digest}"


def _validate_workspace(actor_id: str, body: WorkspaceCreate) -> dict[str, Any]:
    raw_path = body.path.strip()
    if not raw_path:
        raise HTTPException(400, "workspace_path_required")

    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(422, "workspace_path_not_directory")

    try:
        root = Path(_run_git(path, "rev-parse", "--show-toplevel")).resolve()
    except HTTPException as exc:
        raise HTTPException(422, "workspace_path_not_git_repo") from exc
    branch = _run_git(root, "branch", "--show-current")
    try:
        remote_url = _run_git(root, "remote", "get-url", "origin")
    except HTTPException as exc:
        raise HTTPException(422, "workspace_path_missing_origin") from exc
    _validate_azure_devops_remote(remote_url)
    dirty = bool(_run_git(root, "status", "--short"))
    label = (body.label or root.name).strip() or root.name
    now = _now_iso()
    return {
        "id": _workspace_id(actor_id, root, label),
        "label": label,
        "path": str(root),
        "current_branch": branch or None,
        "remote_url": _safe_remote_url(remote_url),
        "is_dirty": dirty,
        "azure_project": body.azure_project,
        "azure_repo": body.azure_repo,
        "created_at": now,
        "updated_at": now,
    }


def _run_worktree_add(source: Path, path: Path, branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing_root = Path(_run_git(path, "rev-parse", "--show-toplevel")).resolve()
            existing_branch = _run_git(existing_root, "branch", "--show-current")
        except HTTPException as exc:
            raise HTTPException(409, "workspace_worktree_path_exists") from exc
        if existing_root == path.resolve() and existing_branch == branch:
            return
        raise HTTPException(409, "workspace_worktree_path_exists")

    branch_exists = (
        _run_git_status(source, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        == 0
    )
    args = ["worktree", "add", str(path), branch]
    if not branch_exists:
        args = ["worktree", "add", "-b", branch, str(path), "HEAD"]
    _run_git(source, *args)


def _prepare_workspace_run_sync(workspace: dict[str, Any], thread_id: str) -> dict[str, Any]:
    source = Path(str(workspace.get("path") or "")).expanduser().resolve()
    if not source.is_dir():
        raise HTTPException(422, "workspace_path_not_directory")
    try:
        root = Path(_run_git(source, "rev-parse", "--show-toplevel")).resolve()
    except HTTPException as exc:
        raise HTTPException(422, "workspace_path_not_git_repo") from exc
    if root != source:
        source = root

    remote_url = _run_git(source, "remote", "get-url", "origin")
    _validate_azure_devops_remote(remote_url)

    base_branch = _run_git(source, "branch", "--show-current") or "HEAD"
    source_dirty = bool(_run_git(source, "status", "--short"))
    if source_dirty and not _allow_dirty_workspace():
        raise HTTPException(409, "workspace_source_dirty")
    branch = _worktree_branch(thread_id)
    worktree = _worktree_path(str(workspace["id"]), thread_id)
    _run_worktree_add(source, worktree, branch)

    return {
        **workspace,
        "source_path": str(source),
        "source_branch": base_branch,
        "source_is_dirty": source_dirty,
        "path": str(worktree),
        "current_branch": branch,
        "remote_url": _safe_remote_url(remote_url),
        "is_dirty": bool(_run_git(worktree, "status", "--short")),
        "worktree_path": str(worktree),
        "worktree_branch": branch,
        "worktree_base_branch": base_branch,
    }


async def _get_value(namespace: list[str], key: str) -> dict[str, Any] | None:
    try:
        item = await _client().store.get_item(namespace, key)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    if item is None:
        return None
    value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
    return value if isinstance(value, dict) else None


async def list_workspaces(actor_id: str) -> list[dict[str, Any]]:
    result = await _client().store.search_items(_namespace(actor_id), limit=200)
    items = result.get("items") if isinstance(result, dict) else getattr(result, "items", [])
    workspaces: list[dict[str, Any]] = []
    for item in items or []:
        value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
        if isinstance(value, dict):
            workspaces.append(value)
    workspaces.sort(key=lambda item: str(item.get("label") or "").lower())
    return workspaces


async def get_workspace(actor_id: str, workspace_id: str | None) -> dict[str, Any] | None:
    if not workspace_id:
        return None
    return await _get_value(_namespace(actor_id), workspace_id)


async def prepare_workspace_run(
    actor_id: str, workspace_id: str | None, thread_id: str
) -> dict[str, Any] | None:
    workspace = await get_workspace(actor_id, workspace_id)
    if not workspace:
        return None
    return await asyncio.to_thread(_prepare_workspace_run_sync, workspace, thread_id)


async def register_workspace(actor_id: str, body: WorkspaceCreate) -> dict[str, Any]:
    value = await asyncio.to_thread(_validate_workspace, actor_id, body)
    existing = await _get_value(_namespace(actor_id), value["id"]) or {}
    value = {
        **existing,
        **value,
        "created_at": existing.get("created_at") or value["created_at"],
        "updated_at": _now_iso(),
    }
    await _client().store.put_item(_namespace(actor_id), value["id"], value)
    return value


def _pick_directory_with_osascript() -> str | None:
    script = 'POSIX path of (choose folder with prompt "Selecciona el proyecto local")'
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


async def pick_and_register_workspace(actor_id: str) -> dict[str, Any]:
    if not _picker_enabled():
        raise HTTPException(403, "workspace_picker_disabled")
    if platform.system() != "Darwin":
        raise HTTPException(501, "workspace_picker_unsupported")

    selected = await asyncio.to_thread(_pick_directory_with_osascript)
    if not selected:
        raise HTTPException(400, "workspace_picker_cancelled")
    return await register_workspace(actor_id, WorkspaceCreate(path=selected))
