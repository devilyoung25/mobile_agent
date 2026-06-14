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
async def test_agent_uses_profile_subagent_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "on-auto-subagent")
    config: RunnableConfig = {
        "configurable": {
            "__is_for_execution__": True,
            "thread_id": "thread-123",
            "actor_id": "github:octocat",
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
    captured: dict[str, object] = {}

    def fake_build_engine(**kwargs: object) -> _DummyAgent:
        captured.update(kwargs)
        return _DummyAgent()

    with (
        patch("agent.server.resolve_triggering_user_identity", return_value=None),
        patch(
            "agent.server.ensure_sandbox_for_thread",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
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
        patch(
            "agent.server.load_profile",
            new_callable=AsyncMock,
            return_value={
                "default_model": "on-auto-coder",
                "reasoning_effort": "medium",
                "default_subagent_model": "on-auto-subagent",
                "subagent_reasoning_effort": "medium",
            },
        ),
        patch("agent.server.get_gateway_models", new_callable=AsyncMock, return_value=[]),
        patch("agent.server.create_model_plan", return_value=model_plan) as create_model_plan,
        patch("agent.server.construct_system_prompt", return_value="prompt"),
        patch("agent.server.build_engine", side_effect=fake_build_engine),
    ):
        await get_agent(config)

    assert captured["model"] is main_model
    assert captured["subagent_model"] is subagent_model

    create_model_plan.assert_called_once_with(
        model_id="on-auto-coder",
        effort="medium",
        subagent_model_id="on-auto-subagent",
        subagent_effort="medium",
        models=[],
        max_tokens=64_000,
    )


@pytest.mark.asyncio
async def test_agent_subagent_inherits_profile_model_override_without_explicit_pair() -> None:
    config: RunnableConfig = {
        "configurable": {
            "__is_for_execution__": True,
            "thread_id": "thread-123",
            "actor_id": "github:octocat",
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
    captured: dict[str, object] = {}

    def fake_build_engine(**kwargs: object) -> _DummyAgent:
        captured.update(kwargs)
        return _DummyAgent()

    with (
        patch("agent.server.resolve_triggering_user_identity", return_value=None),
        patch(
            "agent.server.ensure_sandbox_for_thread",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
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
        patch(
            "agent.server.load_profile",
            new_callable=AsyncMock,
            return_value={
                "default_model": "on-auto-coder",
                "reasoning_effort": "medium",
            },
        ),
        patch("agent.server.get_gateway_models", new_callable=AsyncMock, return_value=[]),
        patch("agent.server.create_model_plan", return_value=model_plan) as create_model_plan,
        patch("agent.server.construct_system_prompt", return_value="prompt"),
        patch("agent.server.build_engine", side_effect=fake_build_engine),
    ):
        await get_agent(config)

    assert captured["subagent_model"] is subagent_model
    create_model_plan.assert_called_once_with(
        model_id="on-auto-coder",
        effort="medium",
        subagent_model_id="on-auto-coder",
        subagent_effort="medium",
        models=[],
        max_tokens=64_000,
    )
