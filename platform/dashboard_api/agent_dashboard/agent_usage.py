"""Per-thread agent usage recording (audit trail for runs)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from langgraph_sdk import get_client

USAGE_THREAD_NAMESPACE: list[str] = ["agent_usage", "threads"]

_AGENT_SOURCES = frozenset({"dashboard", "automation"})

logger = logging.getLogger(__name__)


def _client():
    return get_client()


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _record_from_item(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
    return value if isinstance(value, dict) else None


async def _get_value(namespace: list[str], key: str) -> dict[str, Any] | None:
    try:
        item = await _client().store.get_item(namespace, key)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    return _record_from_item(item)


async def record_agent_thread_usage(
    *,
    thread_id: str,
    actor_id: str | None,
    user_email: str | None,
    model_id: str,
    effort: str | None,
    source: str | None,
) -> None:
    """Record one agent thread for usage auditing."""
    if not thread_id:
        return
    source_value = source if isinstance(source, str) and source in _AGENT_SOURCES else "dashboard"
    now_ms = _now_ms()
    existing = await _get_value(USAGE_THREAD_NAMESPACE, thread_id)
    value = {
        **(existing or {}),
        "thread_id": thread_id,
        "actor_id": actor_id.strip() if isinstance(actor_id, str) else "",
        "user_email": user_email.strip().lower() if isinstance(user_email, str) else "",
        "model_id": model_id,
        "effort": effort or "",
        "source": source_value,
        "agent_kind": "agent",
        "updated_at_ms": now_ms,
    }
    if not existing:
        value["created_at_ms"] = now_ms
    elif not value.get("created_at_ms"):
        value["created_at_ms"] = existing.get("created_at_ms") or now_ms
    await _client().store.put_item(USAGE_THREAD_NAMESPACE, thread_id, value)
