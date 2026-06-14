"""Seam contract between agent-composition and the Capability Gateway.

This is the agreed boundary for the two-lane split (see
``docs/adr/0001-architecture.md``). Composition (lane A) resolves the actor and
their ``project_scope`` and then asks the Capability Gateway (lane B) for the
resolved tools; composition wires the call in ``get_agent``. The gateway
implementation lives in this package and must satisfy :class:`ToolLoader`.

The gateway (lane B) owns, behind this seam:

- resolving which capabilities the ``domain_pack`` requires;
- minting per-actor credentials **server-side** — credentials never reach the LLM
  or the workspace; the neutral engine only ever sees resolved tools;
- applying allow/deny policy and emitting provenance/audit events;
- dispatching to the backing adapters (MCP, REST, SDK, etc.).

``project_scope`` is the list of Azure DevOps project names the actor can access
(produced by ``agent.integrations.azure_devops_mcp.resolve_actor_scope``).
Project-scoped MCPs (e.g. the Business Knowledge MCP) MUST filter their content by
it **server-side**: never serve content for a project outside the scope, even when
the content is hand-curated — that would be a data leak.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_core.tools import BaseTool


@runtime_checkable
class ToolLoader(Protocol):
    """Callable contract the Capability Gateway must satisfy.

    Implemented by lane B in this package; consumed by composition (lane A) in
    ``get_agent``, replacing the current direct ``load_azure_devops_tools_for_actor``
    call. Returns only already-resolved tools (no credentials, no provider detail).
    """

    async def __call__(
        self,
        actor_id: str | None,
        *,
        domain_pack: str,
        project_scope: list[str],
    ) -> list[BaseTool]: ...
