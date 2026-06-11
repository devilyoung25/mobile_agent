"""Provider-neutral commit identity for agent-authored work."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

AGENT_BOT_NAME = "on-mobile-agent[bot]"
AGENT_BOT_EMAIL = "on-mobile-agent@noreply.local"

# Backwards-compatible aliases while the engine extraction is in progress.
OPEN_SWE_BOT_NAME = AGENT_BOT_NAME
OPEN_SWE_BOT_EMAIL = AGENT_BOT_EMAIL


@dataclass(frozen=True)
class CollaboratorIdentity:
    """Identity used for git commit attribution."""

    display_name: str
    commit_name: str
    commit_email: str


def _normalize_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_triggering_user_identity(config: dict[str, Any]) -> CollaboratorIdentity | None:
    """Resolve the triggering user's git identity from run configuration.

    The identity arrives in the run configurable (set by the dashboard from the
    authenticated session); no code-host lookup is performed here.
    """
    configurable = config.get("configurable", {})
    if not isinstance(configurable, dict):
        return None

    commit_email = _normalize_text(configurable.get("user_email"))
    display_name = _normalize_text(configurable.get("user_name")) or commit_email.split("@", 1)[0]
    if display_name and commit_email:
        return CollaboratorIdentity(
            display_name=display_name,
            commit_name=display_name,
            commit_email=commit_email,
        )
    return None


def add_bot_coauthor_trailer(commit_message: str) -> str:
    """Append the agent's Co-authored-by trailer to a commit message."""
    normalized_message = commit_message.rstrip()
    trailer = f"Co-authored-by: {AGENT_BOT_NAME} <{AGENT_BOT_EMAIL}>"
    if trailer in normalized_message:
        return normalized_message
    return f"{normalized_message}\n\n{trailer}"
