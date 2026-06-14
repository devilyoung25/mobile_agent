"""Sandbox-lifecycle resolution for agent composition.

Owns the per-thread sandbox: get-or-create lifecycle, cross-process creation lock,
recreation on transient failure, worktree binding, and the consultative scratch
fallback. Extracted from ``agent/server.py`` without behaviour change. The LangGraph
``client`` and the ``SANDBOX_*`` constants live here; ``server.py`` re-imports the
public names so call sites and patch targets stay coherent.

``resolve_run_sandbox`` is the orchestrator ``get_agent`` calls: it ensures the
sandbox, binds the worktree (or consultative scratch), resolves the work dir, and
returns a backend factory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from deepagents.backends.protocol import SandboxBackendProtocol
from langgraph.graph.state import RunnableConfig
from langgraph_sdk import get_client
from langsmith.sandbox import SandboxClientError

from ..integrations.devcontainer_worktree import create_devcontainer_worktree_sandbox
from ..integrations.local_worktree import LocalWorktreeBackend, create_local_worktree_sandbox
from ..utils.authorship import AGENT_BOT_EMAIL, AGENT_BOT_NAME
from ..utils.sandbox import create_sandbox
from ..utils.sandbox_paths import aresolve_sandbox_work_dir
from ..utils.sandbox_state import (
    SANDBOX_BACKENDS,
    get_sandbox_id_from_metadata,
    set_sandbox_backend,
    unwrap_sandbox_backend,
)

logger = logging.getLogger(__name__)

client = get_client()

SANDBOX_CREATING = "__creating__"
SANDBOX_CREATION_TIMEOUT = 180
SANDBOX_POLL_INTERVAL = 1.0


async def _configure_git_identity(sandbox_backend: SandboxBackendProtocol) -> None:
    await asyncio.to_thread(
        sandbox_backend.execute,
        f"git config --global user.name '{AGENT_BOT_NAME}' && "
        f"git config --global user.email '{AGENT_BOT_EMAIL}'",
    )


async def _create_sandbox_backend() -> SandboxBackendProtocol:
    """Create a new sandbox backend for a thread."""
    return await asyncio.to_thread(create_sandbox)


async def _recreate_sandbox(thread_id: str) -> SandboxBackendProtocol:
    """Recreate a sandbox after a connection failure.

    Sets the SANDBOX_CREATING sentinel and creates a fresh sandbox, swapping
    the per-thread backend. The agent works against the new workspace.
    """
    await client.threads.update(thread_id=thread_id, metadata=_creating_metadata())
    try:
        sandbox_backend = set_sandbox_backend(thread_id, await _create_sandbox_backend())
    except Exception:
        logger.exception("Failed to recreate sandbox after connection failure")
        await client.threads.update(thread_id=thread_id, metadata=_RESET_METADATA)
        raise
    return sandbox_backend


async def _recreate_sandbox_for_thread(thread_id: str) -> str:
    """Composition-side sandbox recreation injected into the neutral engine.

    Passed to ``build_engine(recreate_sandbox=...)`` so ``ToolErrorMiddleware`` can
    recover from a ``SandboxClientError`` without the engine importing this module.
    """
    sandbox_backend = await _recreate_sandbox(thread_id)
    sandbox_backend = set_sandbox_backend(thread_id, sandbox_backend)
    await client.threads.update(thread_id=thread_id, metadata={"sandbox_id": sandbox_backend.id})
    await _configure_git_identity(sandbox_backend)
    return sandbox_backend.id


async def check_or_recreate_sandbox(
    sandbox_backend: SandboxBackendProtocol,
    thread_id: str,
) -> SandboxBackendProtocol:
    """Check if a cached sandbox is reachable; recreate it if not.

    Pings the sandbox with a lightweight command. If the sandbox is
    unreachable (SandboxClientError), it is torn down and a fresh one
    is created via _recreate_sandbox.

    Returns the original backend if healthy, or a new one if recreated.
    """
    try:
        await asyncio.to_thread(sandbox_backend.execute, "echo ok")
    except SandboxClientError:
        logger.warning(
            "Cached sandbox is no longer reachable for thread %s, recreating",
            thread_id,
        )
        sandbox_backend = await _recreate_sandbox(thread_id)
    return sandbox_backend


def _workspace_execution_path(configurable: dict[str, Any]) -> str | None:
    for key in ("workspace_worktree_path", "workspace_path"):
        value = configurable.get(key)
        if isinstance(value, str) and value.startswith("/"):
            return value
    return None


def _is_local_worktree_backend(sandbox_backend: SandboxBackendProtocol) -> bool:
    return isinstance(unwrap_sandbox_backend(sandbox_backend), LocalWorktreeBackend)


# Worktree providers bind a per-thread workspace path as their root. "local" maps
# to the guardrailed local worktree too (its raw backend is never used once a
# workspace is selected).
_WORKTREE_SANDBOX_FACTORIES = {
    "local": create_local_worktree_sandbox,
    "local_worktree": create_local_worktree_sandbox,
    "devcontainer_worktree": create_devcontainer_worktree_sandbox,
}


def _consultative_scratch_dir(thread_id: str) -> str:
    """An isolated, empty per-thread directory for consultative (no-workspace) runs.

    Without a prepared workspace the local sandbox would otherwise root at the
    process cwd (the ON Mobile Agent repo itself), letting a free chat read/explore
    the wrong project. Rooting at an empty scratch dir keeps consultative runs from
    ever seeing the host project; the consultative prompt already tells the agent
    not to touch the filesystem.
    """
    root = os.environ.get("ON_MOBILE_AGENT_CONSULTATIVE_ROOT") or os.path.join(
        os.path.expanduser("~/.on-mobile-agent"), "consultative"
    )
    safe = thread_id.replace("/", "-").replace("..", "-").strip("-") or "thread"
    path = os.path.join(root, safe)
    os.makedirs(path, exist_ok=True)
    return path


async def _bind_local_worktree_sandbox(
    thread_id: str,
    sandbox_backend: SandboxBackendProtocol,
    workspace_path: str | None,
) -> SandboxBackendProtocol:
    """Bind worktree-provider execution to the per-thread root.

    With a prepared workspace → that worktree. Without one → an isolated empty
    scratch dir (consultative mode), so the agent never sees the host project.
    Remote providers (langsmith/daytona/…) are already isolated, so leave them.
    """
    sandbox_type = os.getenv("SANDBOX_TYPE", "langsmith")
    factory = _WORKTREE_SANDBOX_FACTORIES.get(sandbox_type)
    if factory is None:
        if workspace_path:
            raise RuntimeError(
                "workspace_requires_worktree_sandbox: selected local workspaces require "
                "SANDBOX_TYPE=local, local_worktree, or devcontainer_worktree"
            )
        return sandbox_backend

    # _consultative_scratch_dir does blocking filesystem I/O (os.makedirs); run it
    # off the event loop so LangGraph's blockbuster guard doesn't trip.
    if workspace_path:
        bind_root = workspace_path
    else:
        bind_root = await asyncio.to_thread(_consultative_scratch_dir, thread_id)

    current = unwrap_sandbox_backend(sandbox_backend)
    current_root = getattr(current, "root_dir", None)
    if current_root is not None and os.path.abspath(str(current_root)) == os.path.abspath(
        bind_root
    ):
        return sandbox_backend

    mode = "worktree" if workspace_path else "consultative scratch"
    logger.info(
        "Binding %s sandbox for thread %s to %s %s",
        sandbox_type,
        thread_id,
        mode,
        bind_root,
    )
    worktree_backend = await asyncio.to_thread(factory, None, root_dir=bind_root)
    sandbox_backend = set_sandbox_backend(thread_id, worktree_backend)
    try:
        await client.threads.update(
            thread_id=thread_id,
            metadata={"sandbox_id": sandbox_backend.id},
        )
    except Exception:
        logger.debug("Failed to persist worktree sandbox id", exc_info=True)
    return sandbox_backend


def _creating_metadata() -> dict[str, Any]:
    """Metadata that claims the cross-process creation lock with a timestamp."""
    return {"sandbox_id": SANDBOX_CREATING, "sandbox_creating_at": time.time()}


_RESET_METADATA: dict[str, Any] = {"sandbox_id": None, "sandbox_creating_at": None}


async def _resolve_creating_sentinel(thread_id: str) -> str | None:
    """Resolve a ``__creating__`` sentinel seen with no cached backend.

    The sentinel is a cross-process lock: another worker may still be creating
    the sandbox. Poll live thread metadata until it resolves to a real id. Only
    when the sentinel is older than ``SANDBOX_CREATION_TIMEOUT`` (e.g. the
    creating worker was restarted) is it treated as stale: metadata is reset and
    ``None`` is returned so the caller creates a fresh sandbox. A sentinel with
    no timestamp (written before this field existed) is also treated as stale.
    """
    while True:
        thread = await client.threads.get(thread_id)
        metadata = thread.get("metadata", {}) if isinstance(thread, dict) else {}
        sandbox_id = metadata.get("sandbox_id") if isinstance(metadata, dict) else None

        if sandbox_id != SANDBOX_CREATING:
            return sandbox_id if isinstance(sandbox_id, str) else None

        creating_at = metadata.get("sandbox_creating_at") if isinstance(metadata, dict) else None
        age = time.time() - creating_at if isinstance(creating_at, (int, float)) else None
        if age is None or age > SANDBOX_CREATION_TIMEOUT:
            logger.warning(
                "Resetting stale SANDBOX_CREATING for thread %s (age=%s)", thread_id, age
            )
            await client.threads.update(thread_id=thread_id, metadata=_RESET_METADATA)
            return None

        await asyncio.sleep(SANDBOX_POLL_INTERVAL)


def graph_loaded_for_execution(config: RunnableConfig) -> bool:
    """Check if the graph is loaded for actual execution vs introspection."""
    return (
        config["configurable"].get("__is_for_execution__", False)
        if "configurable" in config
        else False
    )


async def ensure_sandbox_for_thread(thread_id: str) -> SandboxBackendProtocol:
    """Get-or-create a healthy sandbox bound to ``thread_id``.

    Implements the four-state lifecycle described in AGENTS.md:

    1. Cached in memory → ping; recreate on ``SandboxClientError``.
    2. Metadata says ``__creating__`` and no cache → wait for the creating
       worker; only reset if the sentinel is proven stale (timestamp/timeout).
    3. No sandbox at all → create one and persist the id.
    4. Metadata has an id but no cache → reconnect; recreate on failure.

    Persists the resulting ``sandbox_id`` to thread metadata, and on the
    first creation/reconnect for this thread initializes git identity.
    """
    sandbox_backend = SANDBOX_BACKENDS.get(thread_id)
    sandbox_id = await get_sandbox_id_from_metadata(thread_id)

    if sandbox_id == SANDBOX_CREATING and not sandbox_backend:
        logger.info("Sandbox creation in progress for thread %s, waiting...", thread_id)
        sandbox_id = await _resolve_creating_sentinel(thread_id)

    if sandbox_backend:
        logger.info("Using cached sandbox backend for thread %s", thread_id)
        sandbox_backend = await check_or_recreate_sandbox(sandbox_backend, thread_id)
    elif sandbox_id is None:
        logger.info("Creating new sandbox for thread %s", thread_id)
        await client.threads.update(thread_id=thread_id, metadata=_creating_metadata())
        try:
            sandbox_backend = await _create_sandbox_backend()
            logger.info("Sandbox created: %s", sandbox_backend.id)
        except Exception:
            logger.exception("Failed to create sandbox")
            try:
                await client.threads.update(thread_id=thread_id, metadata=_RESET_METADATA)
            except Exception:
                logger.exception("Failed to reset sandbox_id metadata")
            raise
    else:
        logger.info("Connecting to existing sandbox %s", sandbox_id)
        try:
            sandbox_backend = await asyncio.to_thread(create_sandbox, sandbox_id)
        except Exception:
            logger.warning("Failed to connect to existing sandbox %s, creating new one", sandbox_id)
            await client.threads.update(thread_id=thread_id, metadata=_creating_metadata())
            try:
                sandbox_backend = await _create_sandbox_backend()
            except Exception:
                logger.exception("Failed to create replacement sandbox")
                await client.threads.update(thread_id=thread_id, metadata=_RESET_METADATA)
                raise
        else:
            sandbox_backend = await check_or_recreate_sandbox(sandbox_backend, thread_id)

    sandbox_backend = set_sandbox_backend(thread_id, sandbox_backend)

    if sandbox_id != sandbox_backend.id:
        await client.threads.update(
            thread_id=thread_id, metadata={"sandbox_id": sandbox_backend.id}
        )

    # Re-apply git identity every run: cached/reconnected sandboxes may have
    # lost their `--global` config (or had it overwritten).
    await _configure_git_identity(sandbox_backend)

    return sandbox_backend


def _get_cached_sandbox_backend(thread_id: str) -> SandboxBackendProtocol:
    sandbox_backend = SANDBOX_BACKENDS.get(thread_id)
    if sandbox_backend is None:
        raise RuntimeError(f"No sandbox backend cached for thread {thread_id}")
    return sandbox_backend


async def resolve_run_sandbox(
    thread_id: str, configurable: dict[str, Any]
) -> tuple[SandboxBackendProtocol, str, str | None, Any]:
    """Ensure + bind the per-thread sandbox and resolve its work dir.

    Returns ``(sandbox_backend, work_dir, workspace_path, backend_factory)``.
    ``get_agent`` runs this as a task in parallel with model-defaults resolution.
    """
    sandbox_backend = await ensure_sandbox_for_thread(thread_id)

    workspace_path = _workspace_execution_path(configurable)
    sandbox_backend = await _bind_local_worktree_sandbox(thread_id, sandbox_backend, workspace_path)
    if _is_local_worktree_backend(sandbox_backend):
        work_dir = "/"
    else:
        work_dir = await aresolve_sandbox_work_dir(sandbox_backend)
        if workspace_path:
            work_dir = workspace_path

    def backend_factory(_runtime: object, _thread_id: str = thread_id) -> SandboxBackendProtocol:
        return _get_cached_sandbox_backend(_thread_id)

    return sandbox_backend, work_dir, workspace_path, backend_factory
