"""Main entry point for the ON Mobile Agent engine graph."""
# ruff: noqa: E402

# Suppress deprecation warnings from langchain_core (e.g., Pydantic V1 on Python 3.14+)
import logging
import os
import time
import warnings
from typing import Any

logger = logging.getLogger(__name__)

from langgraph.graph.state import RunnableConfig
from langgraph.pregel import Pregel
from langgraph_sdk import get_client

warnings.filterwarnings("ignore", module="langchain_core._api.deprecation")

import asyncio

# Suppress Pydantic v1 compatibility warnings from langchain on Python 3.14+
warnings.filterwarnings("ignore", message=".*Pydantic V1.*", category=UserWarning)

from deepagents import create_deep_agent
from deepagents.backends.protocol import SandboxBackendProtocol
from langsmith.sandbox import SandboxClientError
from mcp_toolset import load_tools_for
from on_core import DEFAULT_RECURSION_LIMIT, MODEL_CALL_RECURSION_LIMIT, build_engine

from .composition.approval_resolution import _approval_policy, _has_azure_devops
from .composition.model_resolution import resolve_model_plan
from .composition.prompt_resolution import (
    _resolve_prompt_default_repo,
    _resolve_repo_custom_instructions,
)
from .composition.tool_resolution import (
    _domain_pack,
    _load_observability_tools,
    _observability_authorized,
)
from .dashboard.agent_overrides import (
    load_profile,
    resolve_actor_id,
)
from .dashboard.agent_usage import record_agent_thread_usage
from .dashboard.team_settings import get_team_default_model_pair
from .integrations.azure_devops_mcp import (
    AZURE_DEVOPS_PROMPT_FRAGMENT,
    resolve_actor_scope,
)
from .integrations.devcontainer_worktree import create_devcontainer_worktree_sandbox
from .integrations.local_worktree import LocalWorktreeBackend, create_local_worktree_sandbox
from .prompt import construct_system_prompt
from .tools import (
    fetch_url,
    http_request,
    web_search,
)
from .utils.authorship import (
    AGENT_BOT_EMAIL,
    AGENT_BOT_NAME,
    resolve_triggering_user_identity,
)
from .utils.sandbox import create_sandbox
from .utils.sandbox_paths import aresolve_sandbox_work_dir

client = get_client()

SANDBOX_CREATING = "__creating__"
SANDBOX_CREATION_TIMEOUT = 180
SANDBOX_POLL_INTERVAL = 1.0

from .utils.sandbox_state import (
    SANDBOX_BACKENDS,
    get_sandbox_id_from_metadata,
    set_sandbox_backend,
    unwrap_sandbox_backend,
)

__all__ = ["get_agent", "ensure_sandbox_for_thread", "unwrap_sandbox_backend"]


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


async def get_agent(config: RunnableConfig) -> Pregel:
    """Get or create an agent with a sandbox for the given thread."""
    configurable = (config or {}).get("configurable") or {}
    thread_id = configurable.get("thread_id", None)

    config["recursion_limit"] = DEFAULT_RECURSION_LIMIT

    if thread_id is None or not graph_loaded_for_execution(config):
        logger.info("No thread_id or not for execution, returning agent without sandbox")
        return create_deep_agent(
            system_prompt="",
            tools=[],
        ).with_config(config)

    actor_id = resolve_actor_id(config)
    triggering_user_identity = resolve_triggering_user_identity(config)
    sandbox_task = asyncio.create_task(ensure_sandbox_for_thread(thread_id))
    team_defaults_task = asyncio.create_task(get_team_default_model_pair("agent"))
    profile_task = asyncio.create_task(load_profile(actor_id)) if actor_id else None
    sandbox_backend, team_defaults = await asyncio.gather(sandbox_task, team_defaults_task)
    profile = await profile_task if profile_task is not None else None

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

    model_plan, model_id, profile_effort = await resolve_model_plan(
        actor_id, profile, team_defaults, configurable
    )

    source = (
        configurable.get("source") if isinstance(configurable.get("source"), str) else "dashboard"
    )
    user_email = configurable.get("user_email")
    user_email = user_email if isinstance(user_email, str) else ""
    try:
        await client.threads.update(
            thread_id=thread_id,
            metadata={
                "agent_kind": "agent",
                "model": model_id,
                "effort": profile_effort,
                "source": source,
            },
        )
        await record_agent_thread_usage(
            thread_id=thread_id,
            actor_id=actor_id,
            user_email=user_email,
            model_id=model_id,
            effort=profile_effort,
            source=source,
        )
    except Exception:
        logger.debug("Failed to record agent usage for thread %s", thread_id, exc_info=True)

    prompt_default_repo = await _resolve_prompt_default_repo(configurable)
    repo_custom_instructions = await _resolve_repo_custom_instructions(prompt_default_repo)

    observability_authorized = _observability_authorized(config)
    # Capability Gateway: composition resolves the actor's project scope, then asks
    # the gateway for governed, resolved tools for this domain pack. Credentials and
    # provider detail stay inside the gateway; the engine only sees the tools.
    project_scope, observability_tools = await asyncio.gather(
        resolve_actor_scope(actor_id),
        _load_observability_tools(observability_authorized),
    )
    gateway_tools = await load_tools_for(
        actor_id,
        domain_pack=_domain_pack(configurable),
        project_scope=project_scope,
    )

    logger.info("Returning agent with sandbox for thread %s", thread_id)
    return build_engine(
        model=model_plan.model,
        subagent_model=model_plan.subagent_model,
        system_prompt=construct_system_prompt(
            working_dir=work_dir,
            triggering_user_identity=triggering_user_identity,
            default_repo=prompt_default_repo,
            repo_custom_instructions=repo_custom_instructions,
            mode="workspace" if workspace_path else "consultative",
            integration_policy=AZURE_DEVOPS_PROMPT_FRAGMENT if _has_azure_devops(gateway_tools) else None,
        ),
        tools=[
            http_request,
            fetch_url,
            web_search,
            *gateway_tools,
            *observability_tools,
        ],
        backend=backend_factory,
        run_limit=MODEL_CALL_RECURSION_LIMIT,
        approval_policy=_approval_policy(gateway_tools),
        recreate_sandbox=_recreate_sandbox_for_thread,
    ).with_config(config)
