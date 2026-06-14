"""Prompt-context resolution for agent composition.

Resolves the default repository and per-repo custom agent instructions used to build
the system prompt. Extracted from ``agent/server.py`` without behaviour change.
"""

from __future__ import annotations

import logging
from typing import Any

from ..dashboard.team_settings import get_team_default_repo

logger = logging.getLogger(__name__)


async def _resolve_prompt_default_repo(configurable: dict[str, Any]) -> dict[str, str] | None:
    repo_config = configurable.get("repo")
    if isinstance(repo_config, dict):
        owner = repo_config.get("owner")
        name = repo_config.get("name")
        if isinstance(owner, str) and isinstance(name, str):
            return {"owner": owner, "name": name}

    if configurable.get("repo_explicitly_none") is True:
        return None

    try:
        return await get_team_default_repo()
    except Exception:
        logger.debug("Failed to load team default repo for prompt", exc_info=True)
        return None


async def _resolve_repo_custom_instructions(
    default_repo: dict[str, str] | None,
) -> str | None:
    """Load per-repo custom agent instructions for the resolved default repo."""
    if not default_repo or not default_repo.get("owner") or not default_repo.get("name"):
        return None
    try:
        from ..dashboard.agent_instructions import get_repo_agent_instructions

        return await get_repo_agent_instructions(default_repo["owner"], default_repo["name"])
    except Exception:
        logger.debug("Failed to load repo custom agent instructions", exc_info=True)
        return None
