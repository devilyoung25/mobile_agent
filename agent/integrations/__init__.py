"""Compatibility package for platform integrations."""

from pathlib import Path

from deepagents.backends import LangSmithSandbox

_REAL_INTEGRATIONS = (
    Path(__file__).resolve().parents[2] / "platform" / "integrations" / "agent_integrations"
)
__path__ = [str(_REAL_INTEGRATIONS)]

from agent.integrations.langsmith import LangSmithProvider  # noqa: E402

__all__ = ["LangSmithProvider", "LangSmithSandbox"]
