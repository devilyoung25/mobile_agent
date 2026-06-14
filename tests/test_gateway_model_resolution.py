from unittest.mock import AsyncMock, patch

import pytest
from agent.dashboard.agent_overrides import normalize_profile_overrides
from agent.dashboard.options import default_model_pair, provider_fallback_pair
from agent.dashboard.team_settings import get_team_default_model


def test_provider_fallback_is_disabled_in_agentengine() -> None:
    assert provider_fallback_pair("openai:gpt-5-legacy", "low") is None
    assert provider_fallback_pair("anthropic:claude-opus-legacy", "high") is None


@pytest.mark.asyncio
async def test_team_default_uses_gateway_logical_model() -> None:
    settings = {
        "default_agent_model": "on-auto-coder",
        "default_agent_reasoning_effort": "medium",
    }
    with patch(
        "agent.dashboard.team_settings.get_team_settings",
        new_callable=AsyncMock,
        return_value=settings,
    ):
        assert await get_team_default_model("agent") == ("on-auto-coder", "medium")


@pytest.mark.asyncio
async def test_team_default_unknown_model_falls_back_to_gateway_default() -> None:
    settings = {
        "default_reviewer_model": "openai:gpt-5-legacy",
        "default_reviewer_reasoning_effort": "high",
    }
    with patch(
        "agent.dashboard.team_settings.get_team_settings",
        new_callable=AsyncMock,
        return_value=settings,
    ):
        assert await get_team_default_model("reviewer") == default_model_pair()


def test_profile_gateway_model_override_is_valid() -> None:
    profile = {"default_model": "on-auto-coder", "reasoning_effort": "medium"}
    assert normalize_profile_overrides(profile) == ("on-auto-coder", "medium")


def test_profile_provider_model_defers_to_team_default() -> None:
    profile = {"default_model": "anthropic:claude-opus-legacy", "reasoning_effort": "high"}
    assert normalize_profile_overrides(profile) == (None, None)


def test_global_default_is_gateway_logical_model() -> None:
    assert default_model_pair() == ("on-auto-coder", "medium")
