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
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, SubAgent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langsmith.sandbox import SandboxClientError

from .dashboard.admin import is_observability_authorized
from .dashboard.agent_overrides import (
    load_profile,
    normalize_profile_overrides,
    normalize_profile_subagent_overrides,
    resolve_actor_id,
)
from .dashboard.agent_usage import record_agent_thread_usage
from .dashboard.options import is_supported_model, model_supports_effort
from .dashboard.team_settings import get_team_default_model_pair, get_team_default_repo
from .integrations.azure_devops_mcp import load_azure_devops_read_only_tools
from .integrations.datadog_mcp import load_datadog_tools
from .integrations.langsmith_tools import load_langsmith_tools
from .middleware import (
    ModelFallbackMiddleware,
    SandboxCircuitBreakerMiddleware,
    SanitizeThinkingBlocksMiddleware,
    SanitizeToolInputsMiddleware,
    ToolArtifactMiddleware,
    ToolErrorMiddleware,
    ensure_no_empty_msg,
)
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
from .utils.model import (
    DEFAULT_LLM_REASONING,
    ModelKwargs,
    fallback_model_id_for,
    make_model,
    provider_model_kwargs,
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


async def _resolve_prompt_default_repo(configurable: dict[str, Any]) -> dict[str, str] | None:
    repo_config = configurable.get("repo")
    if isinstance(repo_config, dict):
        owner = repo_config.get("owner")
        name = repo_config.get("name")
        if isinstance(owner, str) and isinstance(name, str):
            return {"owner": owner, "name": name}

    if configurable.get("repo_explicitly_none") is True:
        return None

    try:
        return await get_team_default_repo()
    except Exception:
        logger.debug("Failed to load team default repo for prompt", exc_info=True)
        return None


async def _resolve_repo_custom_instructions(
    default_repo: dict[str, str] | None,
) -> str | None:
    """Load per-repo custom agent instructions for the resolved default repo."""
    if not default_repo or not default_repo.get("owner") or not default_repo.get("name"):
        return None
    try:
        from .dashboard.agent_instructions import get_repo_agent_instructions

        return await get_repo_agent_instructions(default_repo["owner"], default_repo["name"])
    except Exception:
        logger.debug("Failed to load repo custom agent instructions", exc_info=True)
        return None


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


DEFAULT_LLM_MAX_TOKENS = 64_000
DEFAULT_RECURSION_LIMIT = 9_999
MODEL_CALL_RECURSION_LIMIT = 5_000  # ~half the recursion limit to account for tool calls


def _general_purpose_subagent(model: BaseChatModel) -> SubAgent:
    return {
        "name": GENERAL_PURPOSE_SUBAGENT["name"],
        "description": GENERAL_PURPOSE_SUBAGENT["description"],
        "system_prompt": GENERAL_PURPOSE_SUBAGENT["system_prompt"],
        "model": model,
    }


def _get_cached_sandbox_backend(thread_id: str) -> SandboxBackendProtocol:
    sandbox_backend = SANDBOX_BACKENDS.get(thread_id)
    if sandbox_backend is None:
        raise RuntimeError(f"No sandbox backend cached for thread {thread_id}")
    return sandbox_backend


def _observability_authorized(config: RunnableConfig) -> bool:
    """Whether the triggering user may use the team observability tools.

    Gates on admin / explicitly-authorized emails so prompt-injected runs from
    untrusted contributors cannot reach the team's observability data.
    """
    configurable = (config or {}).get("configurable") or {}
    return is_observability_authorized(configurable.get("user_email"))


async def _load_observability_tools(authorized: bool) -> list[Any]:
    """Datadog (MCP) + LangSmith read tools when the team has connected them.

    Credentials live server-side in team settings; the sandbox never holds them.
    Only loaded for authorized (admin / allow-listed) triggering users so an
    untrusted run cannot exfiltrate team observability data. Failures degrade to
    no tools so the agent still starts.
    """
    if not authorized:
        return []
    try:
        datadog_tools, langsmith_tools = await asyncio.gather(
            load_datadog_tools(),
            load_langsmith_tools(),
        )
    except Exception:
        logger.warning("Failed to load observability tools", exc_info=True)
        return []
    return [*datadog_tools, *langsmith_tools]


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

    work_dir = await aresolve_sandbox_work_dir(sandbox_backend)

    def backend_factory(_runtime: object, _thread_id: str = thread_id) -> SandboxBackendProtocol:
        return _get_cached_sandbox_backend(_thread_id)

    (model_id, profile_effort), (subagent_model_id, subagent_effort) = team_defaults
    logger.info("Using team default agent model: model=%s effort=%s", model_id, profile_effort)
    logger.info(
        "Using team default agent subagent model: model=%s effort=%s",
        subagent_model_id,
        subagent_effort,
    )

    if actor_id and profile:
        overridden_model, overridden_effort = normalize_profile_overrides(profile)
        if overridden_model:
            logger.info(
                "Applying dashboard profile override for %s: model=%s effort=%s",
                actor_id,
                overridden_model,
                overridden_effort,
            )
            model_id = overridden_model
            profile_effort = overridden_effort
            subagent_model_id = overridden_model
            subagent_effort = overridden_effort
        overridden_subagent_model, overridden_subagent_effort = (
            normalize_profile_subagent_overrides(profile)
        )
        if overridden_subagent_model:
            logger.info(
                "Applying dashboard profile subagent override for %s: model=%s effort=%s",
                actor_id,
                overridden_subagent_model,
                overridden_subagent_effort,
            )
            subagent_model_id = overridden_subagent_model
            subagent_effort = overridden_subagent_effort

    per_thread_model = configurable.get("agent_model_id")
    per_thread_effort = configurable.get("agent_effort")
    if (
        isinstance(per_thread_model, str)
        and is_supported_model(per_thread_model)
        and isinstance(per_thread_effort, str)
        and model_supports_effort(per_thread_model, per_thread_effort)
    ):
        logger.info(
            "Applying per-thread model override: model=%s effort=%s",
            per_thread_model,
            per_thread_effort,
        )
        model_id = per_thread_model
        profile_effort = per_thread_effort
        subagent_model_id = per_thread_model
        subagent_effort = per_thread_effort

    model_kwargs = provider_model_kwargs(
        model_id,
        profile_effort,
        max_tokens=DEFAULT_LLM_MAX_TOKENS,
    )
    subagent_model_kwargs = provider_model_kwargs(
        subagent_model_id,
        subagent_effort,
        max_tokens=DEFAULT_LLM_MAX_TOKENS,
    )

    fallback_model_id = os.environ.get("LLM_FALLBACK_MODEL_ID") or fallback_model_id_for(model_id)
    fallback_middleware: list[Any] = []
    if fallback_model_id and fallback_model_id != model_id:
        fallback_kwargs: ModelKwargs = {"max_tokens": DEFAULT_LLM_MAX_TOKENS}
        if fallback_model_id.startswith("openai:"):
            fallback_kwargs["reasoning"] = DEFAULT_LLM_REASONING
        fallback_middleware.append(
            ModelFallbackMiddleware(make_model(fallback_model_id, **fallback_kwargs))
        )
        logger.info("Configured model fallback %s -> %s", model_id, fallback_model_id)

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
    azure_devops_tools, observability_tools = await asyncio.gather(
        load_azure_devops_read_only_tools(),
        _load_observability_tools(observability_authorized),
    )

    logger.info("Returning agent with sandbox for thread %s", thread_id)
    main_model = make_model(model_id, **model_kwargs)
    subagent_model = make_model(subagent_model_id, **subagent_model_kwargs)
    return create_deep_agent(
        model=main_model,
        system_prompt=construct_system_prompt(
            working_dir=work_dir,
            triggering_user_identity=triggering_user_identity,
            default_repo=prompt_default_repo,
            repo_custom_instructions=repo_custom_instructions,
            code_host="azure_devops",
        ),
        tools=[
            http_request,
            fetch_url,
            web_search,
            *azure_devops_tools,
            *observability_tools,
        ],
        subagents=[_general_purpose_subagent(subagent_model)],
        backend=backend_factory,
        middleware=[
            SanitizeToolInputsMiddleware(),
            ModelCallLimitMiddleware(run_limit=MODEL_CALL_RECURSION_LIMIT, exit_behavior="end"),
            ToolErrorMiddleware(),
            ToolArtifactMiddleware(),
            ensure_no_empty_msg,
            SandboxCircuitBreakerMiddleware(),
            *fallback_middleware,
            SanitizeThinkingBlocksMiddleware(),
        ],
    ).with_config(config)
