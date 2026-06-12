"""Generic capability provider over any MCP server."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .policy import ToolPolicy, filter_tools

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpToolsetProvider:
    """One MCP server exposed to the engine as a filtered toolset.

    Knowledge/action servers (Azure DevOps today, the Android skills MCP
    tomorrow) are registered as instances of this class — the engine never
    knows the brand, only the resulting tools and the optional prompt
    fragment that teaches it how to use them.
    """

    name: str
    server_config: dict[str, Any]
    policy: ToolPolicy | None = None
    prompt_fragment: str = ""
    timeout_seconds: float = 30.0
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    async def load_tools(self) -> list[Any]:
        """Connect, list tools, and apply the policy. Failures degrade to []."""
        try:
            tools = await self._build_tools()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load MCP tools for %s", self.name, exc_info=True)
            return []
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "MCP %s exposed %d raw tool(s): %s",
                self.name,
                len(tools),
                [getattr(t, "name", "?") for t in tools],
            )
        result = filter_tools(tools, self.policy)
        if result.blocked:
            logger.info(
                "Blocked %d non-allowed MCP tool(s) from %s", len(result.blocked), self.name
            )
            logger.debug("Blocked MCP %s tool(s): %s", self.name, result.blocked)
        logger.info("Loaded %d MCP tool(s) from %s", len(result.allowed), self.name)
        logger.debug(
            "Loaded MCP %s tool(s): %s",
            self.name,
            [getattr(t, "name", "?") for t in result.allowed],
        )
        return result.allowed

    async def _build_tools(self) -> list[Any]:
        def _make_client() -> Any:
            # Imported in a thread: the import chain (mcp -> jsonschema) does
            # blocking filesystem I/O that the ASGI event loop must not run.
            from langchain_mcp_adapters.client import MultiServerMCPClient

            return MultiServerMCPClient({self.name: self.server_config})

        client = await asyncio.to_thread(_make_client)
        return await client.get_tools()
