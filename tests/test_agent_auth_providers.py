from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph.state import RunnableConfig

from agent.server import get_agent, open_pull_request, request_pr_review


class _DummyAgent:
    def with_config(self, config: RunnableConfig) -> "_DummyAgent":
        self.config = config
        return self


@pytest.mark.asyncio
async def test_entra_agent_run_skips_github_token_and_proxy() -> None:
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

    with (
        patch("agent.server.resolve_github_token", new_callable=AsyncMock) as resolve_token,
        patch("agent.server.resolve_triggering_user_identity", return_value=None),
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
            return_value=(("openai:gpt-5.5", "medium"), ("openai:gpt-5.5", "low")),
        ),
        patch("agent.server.load_profile", new_callable=AsyncMock, return_value={}) as load_profile,
        patch("agent.server.fallback_model_id_for", return_value=None),
        patch("agent.server.make_model", side_effect=[main_model, subagent_model]),
        patch("agent.server.construct_system_prompt", return_value="prompt") as prompt,
        patch("agent.server.load_azure_devops_read_only_tools", new_callable=AsyncMock) as ado_tools,
        patch("agent.server.create_deep_agent", return_value=_DummyAgent()) as create_agent,
    ):
        await get_agent(config)

    resolve_token.assert_not_awaited()
    ensure_sandbox.assert_awaited_once_with("thread-123", configure_github_proxy=False)
    load_profile.assert_awaited_once_with("entra:user-oid")
    ado_tools.assert_awaited_once_with(auth_provider="entra")
    assert prompt.call_args.kwargs["code_host"] == "azure_devops"
    loaded_tools = create_agent.call_args.kwargs["tools"]
    assert open_pull_request not in loaded_tools
    assert request_pr_review not in loaded_tools
