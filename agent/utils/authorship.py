"""Commit identity — re-exported from the on-core package."""

from on_core.identity import (
    AGENT_BOT_EMAIL,
    AGENT_BOT_NAME,
    OPEN_SWE_BOT_EMAIL,
    OPEN_SWE_BOT_NAME,
    CollaboratorIdentity,
    add_bot_coauthor_trailer,
    resolve_triggering_user_identity,
)

__all__ = [
    "AGENT_BOT_EMAIL",
    "AGENT_BOT_NAME",
    "OPEN_SWE_BOT_EMAIL",
    "OPEN_SWE_BOT_NAME",
    "CollaboratorIdentity",
    "add_bot_coauthor_trailer",
    "resolve_triggering_user_identity",
]
