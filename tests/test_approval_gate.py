"""Human-approval gate: brand-neutral policy + engine wiring.

The engine gate (``build_engine(approval_policy=...)``) uses langchain's
``HumanInTheLoopMiddleware``; the composition layer supplies the policy. Today the
gate covers state-changing HTTP calls (Azure DevOps writes are filtered out), so
``http_request`` is gated on mutating methods while reads pass through.
"""

import inspect
from unittest.mock import MagicMock

from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
from on_core import build_engine

from agent.server import _approval_policy, _http_request_mutates


def _request(method: str | None) -> MagicMock:
    req = MagicMock()
    req.tool_call = {"name": "http_request", "args": ({"method": method} if method else {})}
    return req


def test_mutating_methods_are_gated() -> None:
    for method in ("POST", "put", "Patch", "DELETE"):
        assert _http_request_mutates(_request(method)) is True


def test_read_methods_are_not_gated() -> None:
    assert _http_request_mutates(_request("GET")) is False
    assert _http_request_mutates(_request(None)) is False  # absent method defaults to GET


def test_policy_constructs_the_real_hitl_middleware() -> None:
    policy = _approval_policy()
    assert "http_request" in policy
    middleware = HumanInTheLoopMiddleware(policy)
    # The middleware accepted our config and registered the gated tool.
    assert "http_request" in middleware.interrupt_on


def test_build_engine_exposes_approval_policy_param() -> None:
    assert "approval_policy" in inspect.signature(build_engine).parameters
