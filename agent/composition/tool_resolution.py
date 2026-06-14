"""Tool-resolution helpers for agent composition.

Selects the domain pack for a run and loads the (authorized) team observability
tools. The Capability Gateway call itself (``load_tools_for``) and the actor scope
resolution stay in ``server.py`` for now. Extracted without behaviour change.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from langgraph.graph.state import RunnableConfig

from ..dashboard.admin import is_observability_authorized
from ..integrations.datadog_mcp import load_datadog_tools
from ..integrations.langsmith_tools import load_langsmith_tools

logger = logging.getLogger(__name__)


def _domain_pack(configurable: dict[str, Any]) -> str:
    """Domain pack for this run (per-run override → env → default ``mobile``)."""
    pack = configurable.get("domain_pack")
    if isinstance(pack, str) and pack.strip():
        return pack.strip()
    return os.environ.get("ON_MOBILE_AGENT_DOMAIN_PACK", "mobile")


def _observability_authorized(config: RunnableConfig) -> bool:
    """Whether the triggering user may use the team observability tools.

    Gates on admin / explicitly-authorized emails so prompt-injected runs from
    untrusted contributors cannot reach the team's observability data.
    """
    configurable = (config or {}).get("configurable") or {}
    return is_observability_authorized(configurable.get("user_email"))


async def _load_observability_tools(authorized: bool) -> list[Any]:
    """Datadog (MCP) + LangSmith read tools when the team has connected them.

    Credentials live server-side in team settings; the sandbox never holds them.
    Only loaded for authorized (admin / allow-listed) triggering users so an
    untrusted run cannot exfiltrate team observability data. Failures degrade to
    no tools so the agent still starts.
    """
    if not authorized:
        return []
    try:
        datadog_tools, langsmith_tools = await asyncio.gather(
            load_datadog_tools(),
            load_langsmith_tools(),
        )
    except Exception:
        logger.warning("Failed to load observability tools", exc_info=True)
        return []
    return [*datadog_tools, *langsmith_tools]
