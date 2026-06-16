"""Resolve the DeveloperProfile for a run from the actor's Azure DevOps access.

Entra is the authority: ``resolve_actor_scope`` lists the projects the actor's
token can see, and the chosen profile is the one whose projects intersect that
scope. There is **no fallback** — if nothing matches, the run fails with a clear
error instead of running with an invented operating context.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from .developer_profiles import DeveloperProfile, developer_profiles

logger = logging.getLogger(__name__)


class ProfileResolutionError(RuntimeError):
    """Raised when no developer profile matches the actor's Azure DevOps access."""


def resolve_developer_profile(
    actor_id: str | None,
    actor_scope: Sequence[str],
) -> DeveloperProfile:
    """Select the developer profile whose projects the actor can access.

    ``actor_scope`` is the actor's accessible Azure DevOps project names (from
    ``resolve_actor_scope``). Raises :class:`ProfileResolutionError` when no
    profile matches.
    """
    profiles = developer_profiles()
    matches = [profile for profile in profiles if profile.matches_scope(actor_scope)]
    if not matches:
        raise ProfileResolutionError(
            "No developer profile matches "
            f"actor={actor_id or '<none>'} scope={sorted(actor_scope)}; "
            f"available={[profile.id for profile in profiles]}"
        )
    if len(matches) > 1:
        logger.warning(
            "Multiple developer profiles match actor=%s scope=%s: %s; using %s",
            actor_id,
            sorted(actor_scope),
            [profile.id for profile in matches],
            matches[0].id,
        )
    return matches[0]
