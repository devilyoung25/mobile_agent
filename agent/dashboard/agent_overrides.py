"""Profile lookup + override helpers consumed by ``agent.server.get_agent``."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langgraph_sdk import get_client

from .options import SUPPORTED_MODEL_IDS, model_supports_effort, provider_fallback_pair
from .profiles import PROFILES_NAMESPACE

logger = logging.getLogger(__name__)


def resolve_actor_id(config: dict[str, Any]) -> str | None:
    """Resolve the triggering actor id (``provider:subject``) from run config."""
    configurable = (config or {}).get("configurable") or {}
    actor_id = configurable.get("actor_id")
    if isinstance(actor_id, str) and actor_id.strip():
        return actor_id.strip()
    return None


async def get_profile_default_repo(login: str | None) -> dict[str, str] | None:
    """Return ``{"owner", "name"}`` for the user's profile default_repo, if set."""
    if not login:
        return None
    profile = await load_profile(login)
    if not profile:
        return None
    default_repo = profile.get("default_repo")
    if not isinstance(default_repo, str):
        return None
    parts = default_repo.strip().split("/", 1)
    if len(parts) != 2:
        return None
    owner, name = parts[0].strip(), parts[1].strip()
    if not owner or not name:
        return None
    return {"owner": owner, "name": name}


async def load_profile(login: str) -> dict[str, Any] | None:
    try:
        item = await get_client().store.get_item(PROFILES_NAMESPACE, login)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        logger.warning("profile lookup failed for %s: %s", login, e)
        return None
    if item is None:
        return None
    value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
    return value if isinstance(value, dict) else None


def _normalize_profile_model_pair(
    profile: dict[str, Any],
    *,
    model_key: str,
    effort_key: str,
) -> tuple[str | None, str | None]:
    model_id = profile.get(model_key)
    effort = profile.get(effort_key)
    if (
        isinstance(model_id, str)
        and model_id in SUPPORTED_MODEL_IDS
        and isinstance(effort, str)
        and model_supports_effort(model_id, effort)
    ):
        return model_id, effort
    # A stored selection whose exact id dropped out of the supported set (e.g. an
    # Opus minor-version bump) stays on its provider rather than being discarded
    # and silently deferring to the team default. An absent/unknown-provider
    # selection still returns (None, None) so the team default applies.
    if isinstance(model_id, str):
        provider_pair = provider_fallback_pair(model_id, effort)
        if provider_pair is not None:
            return provider_pair
    return None, None


def normalize_profile_overrides(profile: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(model_id, reasoning_effort)`` if both are valid, else ``(None, None)``."""
    return _normalize_profile_model_pair(
        profile,
        model_key="default_model",
        effort_key="reasoning_effort",
    )


def normalize_profile_subagent_overrides(
    profile: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return the profile's subagent model pair if valid, else ``(None, None)``."""
    return _normalize_profile_model_pair(
        profile,
        model_key="default_subagent_model",
        effort_key="subagent_reasoning_effort",
    )
