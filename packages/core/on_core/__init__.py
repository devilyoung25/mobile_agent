"""ON Mobile Agent engine core: brand-free agent assembly, prompt, middleware."""

from .engine import (
    DEFAULT_RECURSION_LIMIT,
    MODEL_CALL_RECURSION_LIMIT,
    build_engine,
    general_purpose_subagent,
)
from .identity import (
    AGENT_BOT_EMAIL,
    AGENT_BOT_NAME,
    CollaboratorIdentity,
    add_bot_coauthor_trailer,
    resolve_triggering_user_identity,
)
from .prompt import construct_system_prompt

__all__ = [
    "AGENT_BOT_EMAIL",
    "AGENT_BOT_NAME",
    "DEFAULT_RECURSION_LIMIT",
    "MODEL_CALL_RECURSION_LIMIT",
    "CollaboratorIdentity",
    "add_bot_coauthor_trailer",
    "build_engine",
    "construct_system_prompt",
    "general_purpose_subagent",
    "resolve_triggering_user_identity",
]
