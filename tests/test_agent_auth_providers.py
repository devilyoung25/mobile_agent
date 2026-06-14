from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph.state import RunnableConfig

from agent.server import get_agent


class _DummyAgent:
    def with_config(self, config: RunnableConfig) -> "_DummyAgent":
        self.config = config
        return self


@pytest.mark.asyncio
async def test_engine_run_uses_actor_identity_and_azure_devops_tools() -> None:
    config: RunnableConfig = {
        "configurable": {
            "__is_for_execution__": True,
            "thread_id": "thread-123",
            "source": "dashboard",
            "auth_provider": "entra",
            "actor_id": "entra:user-oid",
            "user_email": "dev@example.com",
        },
        "metadata": {},
    }
    main_model = MagicMock(name="main_model")
    subagent_model = MagicMock(name="subagent_model")
    model_plan = SimpleNamespace(
        model=main_model,
        subagent_model=subagent_model,
        model_id="on-auto-coder",
    )
    ado_tool = MagicMock(name="ado_tool")

    with (
        patch(
            "agent.server.ensure_sandbox_for_thread",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as ensure_sandbox,
        patch(
            "agent.server.aresolve_sandbox_work_dir",
            new_callable=AsyncMock,
            return_value="/workspace",
        ),
        patch(
            "agent.server.get_team_default_model_pair",
            new_callable=AsyncMock,
            return_value=(("on-auto-coder", "medium"), ("on-auto-coder", "medium")),
        ),
        patch("agent.server.load_profile", new_callable=AsyncMock, return_value={}) as load_profile,
        patch("agent.server.client") as fake_client,
        patch("agent.server.record_agent_thread_usage", new_callable=AsyncMock) as record_usage,
        patch("agent.server.get_gateway_models", new_callable=AsyncMock, return_value=[]),
        patch("agent.server.create_model_plan", return_value=model_plan),
        patch("agent.server.construct_system_prompt", return_value="prompt") as prompt,
        patch(
            "agent.server.load_azure_devops_tools_for_actor",
            new_callable=AsyncMock,
            return_value=[ado_tool],
        ) as ado_tools,
        patch("agent.server.build_engine", return_value=_DummyAgent()) as build_engine,
    ):
        fake_client.threads.update = AsyncMock()
        await get_agent(config)

    ensure_sandbox.assert_awaited_once_with("thread-123")
    load_profile.assert_awaited_once_with("entra:user-oid")
    ado_tools.assert_awaited_once_with("entra:user-oid")
    assert record_usage.await_args.kwargs["actor_id"] == "entra:user-oid"
    # Azure policy is injected into the prompt as integration policy (provider-neutral
    # engine) whenever Azure DevOps tools are loaded — replaces the old `code_host` arg.
    assert prompt.call_args.kwargs["integration_policy"] is not None
    loaded_tools = build_engine.call_args.kwargs["tools"]
    assert ado_tool in loaded_tools
    tool_names = {getattr(t, "__name__", getattr(t, "name", "")) for t in loaded_tools}
    assert "open_pull_request" not in tool_names
    assert "request_pr_review" not in tool_names
