"""Compatibility package for the dashboard backend.

The implementation lives under ``platform/dashboard_api``; keep
``agent.dashboard`` import paths stable while the platform layer is split out.
"""

from pathlib import Path

_REAL_DASHBOARD = (
    Path(__file__).resolve().parents[2] / "platform" / "dashboard_api" / "agent_dashboard"
)
__path__ = [str(_REAL_DASHBOARD)]

from .routes import router  # noqa: E402

__all__ = ["router"]
