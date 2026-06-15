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
DEFAULT_INTEGRATION_BRANCH = "develop"
# Identity for the develop-merge commit created when binding a local_branch worktree.
# Never the dev's identity; this commit is synthetic prep, not authored work.
_WORKTREE_MERGE_USER_NAME = "ON Mobile Agent"
_WORKTREE_MERGE_USER_EMAIL = "on-mobile-agent@noreply.local"
_BASE_MODE_INTEGRATION = "integration"
_BASE_MODE_LOCAL_BRANCH = "local_branch"


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


def _allow_nonazure_workspace() -> bool:
    """Escape hatch (default OFF): allow workspaces whose origin is not Azure DevOps.

    The platform is Azure DevOps-first, so by default only Azure remotes are
    accepted. Set ``ON_MOBILE_AGENT_ALLOW_NONAZURE_WORKSPACE=1`` for local
    testing against non-Azure repos. Surfaced to the dashboard via ``/me`` so the
    UI can mirror the policy.
    """
    return _truthy(os.environ.get("ON_MOBILE_AGENT_ALLOW_NONAZURE_WORKSPACE"))


def _validate_azure_devops_remote(url: str | None) -> None:
    if _allow_nonazure_workspace():
        return
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


def _allow_stale_integration() -> bool:
    """Escape hatch (default OFF) to work offline with a cached integration branch.

    The contract is "the agent always starts from the latest develop/integration",
    so a failed fetch fails the run closed (workspace_fetch_failed). Set
    ``ON_MOBILE_AGENT_ALLOW_STALE_INTEGRATION=1`` to proceed with the last-known
    ``origin/<integration>`` — the run is then recorded with ``integration_synced``
    false so the UI/snapshot can flag that develop may not be the latest.
    """
    return _truthy(os.environ.get("ON_MOBILE_AGENT_ALLOW_STALE_INTEGRATION"))


def _integration_branch(workspace: dict[str, Any]) -> str:
    configured = (workspace.get("integration_branch") or "").strip()
    if configured:
        return configured
    env_branch = (os.environ.get("ON_MOBILE_AGENT_INTEGRATION_BRANCH") or "").strip()
    return env_branch or DEFAULT_INTEGRATION_BRANCH


def _base_mode(workspace: dict[str, Any], override: str | None) -> str:
    candidate = (override or workspace.get("default_base_mode") or _BASE_MODE_INTEGRATION).strip()
    if candidate not in {_BASE_MODE_INTEGRATION, _BASE_MODE_LOCAL_BRANCH}:
        raise HTTPException(422, "workspace_base_mode_invalid")
    return candidate


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


def _git_env() -> dict[str, str]:
    """Non-interactive git env so a credential-less fetch fails fast (never hangs)."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("GCM_INTERACTIVE", "never")
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    return env


def _fetch_origin(source: Path, *refs: str, timeout: int = 60) -> bool:
    """Best-effort ``git fetch`` of the given refs from origin.

    Returns ``True`` on success, ``False`` otherwise. Never raises and never
    surfaces git stderr (it can carry the remote URL / credential hints); the
    caller falls back to whatever ``origin/<ref>`` already resolves locally.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "fetch", "--prune", "--no-tags", "origin", *refs],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(),
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def _rev_parse(source: Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    sha = result.stdout.strip()
    return sha or None


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


def _run_worktree_add(source: Path, path: Path, branch: str, start_point: str) -> bool:
    """Create the per-thread worktree branch from ``start_point``.

    Returns ``True`` if a new worktree was created, ``False`` if it already existed
    (idempotent re-prep for the same thread). Raises 409 if the path exists but is
    not our worktree on the expected branch.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing_root = Path(_run_git(path, "rev-parse", "--show-toplevel")).resolve()
            existing_branch = _run_git(existing_root, "branch", "--show-current")
        except HTTPException as exc:
            raise HTTPException(409, "workspace_worktree_path_exists") from exc
        if existing_root == path.resolve() and existing_branch == branch:
            return False
        raise HTTPException(409, "workspace_worktree_path_exists")

    branch_exists = (
        _run_git_status(source, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        == 0
    )
    args = ["worktree", "add", str(path), branch]
    if not branch_exists:
        args = ["worktree", "add", "-b", branch, str(path), start_point]
    _run_git(source, *args)
    return True


def _remove_worktree(source: Path, worktree: Path, branch: str) -> None:
    """Best-effort teardown of a worktree and its branch (used on merge failure)."""
    subprocess.run(
        ["git", "-C", str(source), "worktree", "remove", "--force", str(worktree)],
        check=False, capture_output=True, text=True, timeout=20,
    )
    subprocess.run(
        ["git", "-C", str(source), "branch", "-D", branch],
        check=False, capture_output=True, text=True, timeout=10,
    )


def _worktree_merge_integration(
    source: Path, worktree: Path, branch: str, integration: str
) -> None:
    """Merge ``origin/<integration>`` (develop) into a fresh local_branch worktree.

    On conflict, abort the merge and tear down the worktree+branch, then raise 409
    so the dev resolves the divergence with develop before retrying. The merge commit
    is authored by the synthetic agent identity, never the dev's.
    """
    merge = subprocess.run(
        [
            "git", "-C", str(worktree),
            "-c", f"user.name={_WORKTREE_MERGE_USER_NAME}",
            "-c", f"user.email={_WORKTREE_MERGE_USER_EMAIL}",
            "merge", "--no-edit", f"origin/{integration}",
        ],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if merge.returncode != 0:
        subprocess.run(
            ["git", "-C", str(worktree), "merge", "--abort"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        _remove_worktree(source, worktree, branch)
        raise HTTPException(409, "workspace_integration_merge_conflict")


def _prepare_workspace_run_sync(
    workspace: dict[str, Any], thread_id: str, *, base_mode: str | None = None
) -> dict[str, Any]:
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

    source_branch = _run_git(source, "branch", "--show-current")
    source_dirty = bool(_run_git(source, "status", "--short"))
    if source_dirty and not _allow_dirty_workspace():
        raise HTTPException(409, "workspace_source_dirty")
    # Lock the dev's branch HEAD at sandbox creation; the future merge-back validates
    # the branch hasn't moved since (and is clean) before integrating the agent's work.
    source_commit = _rev_parse(source, "HEAD")

    integration = _integration_branch(workspace)
    mode = _base_mode(workspace, base_mode)

    # Contract: the agent always starts from the LATEST integration branch (develop).
    # Fetch fails closed unless the offline escape is set (then we proceed on the
    # cached ref with integration_synced=False so callers know it may be stale).
    synced = _fetch_origin(source, integration)
    integration_commit = _rev_parse(source, f"origin/{integration}")
    if integration_commit is None:
        # The branch doesn't exist anywhere (not just unfetchable) -> config error.
        raise HTTPException(422, "workspace_integration_branch_missing")
    if not synced and not _allow_stale_integration():
        # Branch exists (cached) but we couldn't refresh it -> fail closed on the
        # "always latest develop" contract unless the offline escape is set.
        raise HTTPException(502, "workspace_fetch_failed")

    branch = _worktree_branch(thread_id)
    worktree = _worktree_path(str(workspace["id"]), thread_id)

    if mode == _BASE_MODE_LOCAL_BRANCH:
        # New isolated branch off the dev's local branch, with develop merged on top.
        # The dev's real branch is never touched; on approval the work merges back here.
        if not source_branch:
            raise HTTPException(422, "workspace_base_branch_required")
        created = _run_worktree_add(source, worktree, branch, start_point=source_branch)
        if created:
            _worktree_merge_integration(source, worktree, branch, integration)
        base_commit = _run_git(worktree, "rev-parse", "HEAD")
        integration_target = source_branch
    else:
        # New isolated branch straight from the freshly-fetched integration tip.
        created = _run_worktree_add(
            source, worktree, branch, start_point=f"origin/{integration}"
        )
        base_commit = integration_commit
        integration_target = integration

    return {
        **workspace,
        "source_path": str(source),
        "source_branch": source_branch or None,
        "source_commit": source_commit,
        "source_is_dirty": source_dirty,
        "base_mode": mode,
        "integration_branch": integration,
        "integration_commit": integration_commit,
        "integration_target": integration_target,
        "integration_synced": synced,
        "path": str(worktree),
        "current_branch": branch,
        "remote_url": _safe_remote_url(remote_url),
        "is_dirty": bool(_run_git(worktree, "status", "--short")),
        "worktree_path": str(worktree),
        "worktree_branch": branch,
        "worktree_base_branch": integration_target,
        "worktree_base_commit": base_commit,
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
    actor_id: str, workspace_id: str | None, thread_id: str, *, base_mode: str | None = None
) -> dict[str, Any] | None:
    workspace = await get_workspace(actor_id, workspace_id)
    if not workspace:
        return None
    return await asyncio.to_thread(
        _prepare_workspace_run_sync, workspace, thread_id, base_mode=base_mode
    )


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
