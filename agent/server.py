"""Main entry point for the ON Mobile Agent engine graph."""
# ruff: noqa: E402

# Suppress deprecation warnings from langchain_core (e.g., Pydantic V1 on Python 3.14+)
import logging
import warnings

logger = logging.getLogger(__name__)

from langgraph.graph.state import RunnableConfig
from langgraph.pregel import Pregel

warnings.filterwarnings("ignore", module="langchain_core._api.deprecation")

import asyncio

# Suppress Pydantic v1 compatibility warnings from langchain on Python 3.14+
warnings.filterwarnings("ignore", message=".*Pydantic V1.*", category=UserWarning)

from capability_gateway import load_tools_for
from deepagents import create_deep_agent
from on_core import DEFAULT_RECURSION_LIMIT, MODEL_CALL_RECURSION_LIMIT, build_engine

from .composition.approval_resolution import _approval_policy, _has_azure_devops
from .composition.context_resolution import resolve_operating_context
from .composition.model_resolution import resolve_model_plan
from .composition.profile_resolution import resolve_developer_profile
from .composition.prompt_resolution import (
    _resolve_prompt_default_repo,
    _resolve_repo_custom_instructions,
)
from .composition.sandbox_resolution import (
    _recreate_sandbox_for_thread,
    client,
    ensure_sandbox_for_thread,
    graph_loaded_for_execution,
    resolve_run_sandbox,
)
from .composition.tool_resolution import (
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
from .prompt import construct_system_prompt
from .tools import (
    fetch_url,
    http_request,
    web_search,
)
from .utils.authorship import (
    resolve_triggering_user_identity,
)
from .utils.sandbox_state import unwrap_sandbox_backend

__all__ = ["get_agent", "ensure_sandbox_for_thread", "unwrap_sandbox_backend"]


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
    sandbox_task = asyncio.create_task(resolve_run_sandbox(thread_id, configurable))
    team_defaults_task = asyncio.create_task(get_team_default_model_pair("agent"))
    profile_task = asyncio.create_task(load_profile(actor_id)) if actor_id else None
    (_sandbox_backend, work_dir, workspace_path, backend_factory), team_defaults = (
        await asyncio.gather(sandbox_task, team_defaults_task)
    )
    profile = await profile_task if profile_task is not None else None

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
    # Capability Gateway: composition resolves the actor's Azure DevOps access,
    # selects the DeveloperProfile for the run, and asks the gateway for governed,
    # resolved tools scoped to the profile. Entra stays the authority; the profile
    # only narrows scope and the engine only ever sees resolved tools.
    actor_scope, observability_tools = await asyncio.gather(
        resolve_actor_scope(actor_id),
        _load_observability_tools(observability_authorized),
    )
    developer_profile = resolve_developer_profile(actor_id, actor_scope)
    gateway_tools = await load_tools_for(
        actor_id,
        domain_pack=developer_profile.domain_pack,
        project_scope=developer_profile.effective_scope(actor_scope),
    )

    # The TaskResolver (run-creation) classifies the request into a task_kind; the
    # ContextResolver turns the profile + task into the run's operating context,
    # rendered as neutral prompt text (the engine never knows the brand/profile).
    task_kind = configurable.get("task_kind")
    task_kind = task_kind.strip() if isinstance(task_kind, str) and task_kind.strip() else None
    operating_context = (
        await resolve_operating_context(developer_profile, task_kind, actor_scope)
    ).render()

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
            operating_context=operating_context,
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
