"""Approval-policy resolution for agent composition.

The human-approval gate *mechanism* lives in the neutral engine; here composition
derives WHICH actions require approval: a mutating ``http_request`` plus any
Capability Gateway tool whose descriptor declared ``requires_approval``. Extracted
from ``agent/server.py`` without behaviour change.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig

_MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _http_request_mutates(request: Any) -> bool:
    """True when an ``http_request`` tool call would change remote state."""
    args = request.tool_call.get("args") if hasattr(request, "tool_call") else None
    method = str((args or {}).get("method", "GET")).upper()
    return method in _MUTATING_HTTP_METHODS


def _capability_meta(tool: Any) -> dict[str, Any]:
    """Non-sensitive capability metadata attached by the Capability Gateway."""
    meta = getattr(tool, "metadata", None)
    cap = meta.get("capability") if isinstance(meta, dict) else None
    return cap if isinstance(cap, dict) else {}


def _has_azure_devops(tools: list[Any]) -> bool:
    """True when the resolved capability tools include the Azure DevOps origin."""
    return any("azure-devops" in _capability_meta(tool).get("provenance_tags", []) for tool in tools)


def _approval_policy(gateway_tools: list[Any] | None = None) -> dict[str, Any]:
    """Human-approval gate policy (brand-neutral ``interrupt_on`` for the engine).

    Gates a state-changing ``http_request`` on mutating methods (reads pass
    through), plus any Capability Gateway tool whose descriptor declared
    ``requires_approval``. The gate mechanism lives in the neutral engine; the
    Capability Gateway is the source of truth for *which* capabilities need it.
    """
    policy: dict[str, Any] = {
        "http_request": InterruptOnConfig(
            allowed_decisions=["approve", "reject"],
            when=_http_request_mutates,
            description=(
                "This sends a state-changing HTTP request (a persistent action) and "
                "requires human approval before it runs."
            ),
        )
    }
    for tool in gateway_tools or []:
        if _capability_meta(tool).get("requires_approval"):
            policy[tool.name] = InterruptOnConfig(
                allowed_decisions=["approve", "reject"],
                description=(
                    f"This invokes the gated capability '{tool.name}' (a persistent "
                    "action) and requires human approval before it runs."
                ),
            )
    return policy
