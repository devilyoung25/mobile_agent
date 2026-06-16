"""End-to-end composition wiring: profile → task → context → gateway + prompt.

Drives ``get_agent`` with the real resolvers (profile/context/prompt are not
mocked) and asserts the run is scoped by the DeveloperProfile and the operating
context lands in the system prompt. Azure DevOps scope comes from conftest env.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.graph.state import RunnableConfig

from agent.server import get_agent


class _DummyAgent:
    def with_config(self, config: RunnableConfig) -> _DummyAgent:
        self.config = config
        return self


async def test_get_agent_scopes_gateway_and_injects_operating_context() -> None:
    config: RunnableConfig = {
        "configurable": {
            "__is_for_execution__": True,
            "thread_id": "thread-xyz",
            "source": "dashboard",
            "actor_id": "entra:user-oid",
            "user_email": "dev@example.com",
            "task_kind": "bug_analysis",  # set by the TaskResolver at run creation
        },
        "metadata": {},
    }
    model_plan = SimpleNamespace(
        model=MagicMock(name="model"),
        subagent_model=MagicMock(name="subagent"),
        model_id="on-auto-coder",
    )
    captured: dict[str, object] = {}

    def fake_build_engine(**kwargs: object) -> _DummyAgent:
        captured.update(kwargs)
        return _DummyAgent()

    with (
        patch("agent.server.resolve_triggering_user_identity", return_value=None),
        patch(
            "agent.server.resolve_run_sandbox",
            new_callable=AsyncMock,
            return_value=(MagicMock(), "/workspace", "/workspace", lambda *_a, **_k: MagicMock()),
        ),
        patch(
            "agent.server.get_team_default_model_pair",
            new_callable=AsyncMock,
            return_value=(("on-auto-coder", "medium"), ("on-auto-coder", "medium")),
        ),
        patch("agent.server.load_profile", new_callable=AsyncMock, return_value={}),
        patch("agent.server.client") as fake_client,
        patch("agent.server.record_agent_thread_usage", new_callable=AsyncMock),
        patch(
            "agent.composition.model_resolution.get_gateway_models",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("agent.composition.model_resolution.create_model_plan", return_value=model_plan),
        patch(
            "agent.server.resolve_actor_scope",
            new_callable=AsyncMock,
            return_value=["TryController 2.0", "DevSecOps"],  # 1 in-profile, 1 not
        ),
        patch("agent.server.load_tools_for", new_callable=AsyncMock, return_value=[]) as load_tools,
        patch("agent.server.build_engine", side_effect=fake_build_engine),
    ):
        fake_client.threads.update = AsyncMock()
        await get_agent(config)

    # Gateway fed from the profile: domain pack + effective (intersected) scope.
    load_tools.assert_awaited_once_with(
        "entra:user-oid", domain_pack="mobile", project_scope=["TryController 2.0"]
    )

    # construct_system_prompt ran for real → operating context is in the prompt.
    prompt = captured["system_prompt"]
    assert isinstance(prompt, str)
    assert "Operating context" in prompt
    assert "android-kotlin" in prompt
    assert "TryController 2.0" in prompt
    assert "DevSecOps" not in prompt  # out-of-profile project must not leak in
    assert "Task kind: bug_analysis" in prompt

    # Profile/task metadata is persisted for UI/audit (merged across update calls).
    persisted: dict[str, object] = {}
    for call in fake_client.threads.update.await_args_list:
        persisted.update(call.kwargs.get("metadata", {}))
    assert persisted.get("developer_profile_id") == "trycontroller_android"
    assert persisted.get("task_kind") == "bug_analysis"
    assert persisted.get("effective_project_scope") == ["TryController 2.0"]
