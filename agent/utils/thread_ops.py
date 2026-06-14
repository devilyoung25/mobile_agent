"""Shared LangGraph thread helpers for webhooks and the dashboard."""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

from langgraph_sdk import get_client

logger = logging.getLogger(__name__)

_QUEUE_KEY = "pending_messages"


def _queue_namespace(thread_id: str) -> tuple[str, str]:
    return ("queue", thread_id)


def _message_matches(message: dict[str, Any], index: int, message_id: str) -> bool:
    current_id = message.get("id")
    return current_id == message_id or f"queued-{index}" == message_id


async def _read_queue(client: Any, thread_id: str) -> list[dict[str, Any]]:
    try:
        existing_item = await client.store.get_item(_queue_namespace(thread_id), _QUEUE_KEY)
    except Exception:  # noqa: BLE001
        logger.debug("No existing queued messages for thread %s", thread_id)
        return []
    value = existing_item.get("value") if isinstance(existing_item, dict) else None
    messages = value.get("messages") if isinstance(value, dict) else None
    return [message for message in messages if isinstance(message, dict)] if isinstance(messages, list) else []


async def _write_queue(client: Any, thread_id: str, messages: list[dict[str, Any]]) -> None:
    namespace = _queue_namespace(thread_id)
    if not messages:
        await client.store.delete_item(namespace, _QUEUE_KEY)
        return
    await client.store.put_item(namespace, _QUEUE_KEY, {"messages": messages})


def langgraph_url() -> str:
    return os.environ.get("LANGGRAPH_URL") or os.environ.get(
        "LANGGRAPH_URL_PROD", "http://localhost:2024"
    )


def langgraph_client():
    return get_client(url=langgraph_url())


async def get_thread_active_status(thread_id: str) -> bool | None:
    """Return whether the thread is active, or None when status cannot be determined."""
    try:
        thread = await langgraph_client().threads.get(thread_id)
        status = thread.get("status", "idle") if isinstance(thread, dict) else "idle"
        logger.info("Thread %s status check: status=%s", thread_id, status)
        return status == "busy"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get thread status for %s: %s", thread_id, exc)
        return None


async def is_thread_active(thread_id: str) -> bool:
    """Return whether the thread currently has a running run."""
    return await get_thread_active_status(thread_id) is True


async def queue_message_for_thread(
    thread_id: str, message_content: str | list[dict[str, Any]] | dict[str, Any]
) -> bool:
    """Queue a follow-up message for after the active run completes."""
    client = langgraph_client()
    try:
        new_message = {
            "id": uuid4().hex,
            "content": message_content,
            "force_for_active_run": False,
        }
        existing_messages = await _read_queue(client, thread_id)
        existing_messages.append(new_message)
        await _write_queue(client, thread_id, existing_messages)
        logger.info(
            "Queued message for thread %s (total queued: %d)",
            thread_id,
            len(existing_messages),
        )
        return True
    except Exception:
        logger.exception("Failed to queue message for thread %s", thread_id)
        return False


async def get_queued_messages_for_thread(thread_id: str) -> list[dict[str, Any]]:
    """Return queued follow-up messages for a thread without mutating the queue."""
    return await _read_queue(langgraph_client(), thread_id)


async def should_force_queued_messages_for_thread(thread_id: str) -> bool:
    """Return whether queued messages should be injected into the active run."""
    client = langgraph_client()
    try:
        item = await client.store.get_item(_queue_namespace(thread_id), _QUEUE_KEY)
    except Exception:  # noqa: BLE001
        logger.debug("No queued messages for thread %s", thread_id)
        return False
    value = item.get("value") if isinstance(item, dict) else None
    if not isinstance(value, dict):
        return False
    if value.get("force_for_active_run") is True:
        return True
    messages = value.get("messages")
    return (
        any(message.get("force_for_active_run") is True for message in messages if isinstance(message, dict))
        if isinstance(messages, list)
        else False
    )


async def force_queued_messages_for_thread(thread_id: str) -> bool:
    """Allow the active run to consume the queued follow-up messages."""
    client = langgraph_client()
    messages = await get_queued_messages_for_thread(thread_id)
    if not messages:
        return False
    await _write_queue(
        client,
        thread_id,
        [{**message, "force_for_active_run": True} for message in messages],
    )
    return True


async def force_queued_message_for_thread(thread_id: str, message_id: str) -> bool:
    """Allow one queued follow-up message to be consumed by the active run."""
    client = langgraph_client()
    messages = await get_queued_messages_for_thread(thread_id)
    changed = False
    next_messages: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if _message_matches(message, index, message_id):
            next_messages.append({**message, "force_for_active_run": True})
            changed = True
        else:
            next_messages.append(message)
    if not changed:
        return False
    await _write_queue(client, thread_id, next_messages)
    return True


async def pop_queued_message_for_thread(thread_id: str, message_id: str) -> dict[str, Any] | None:
    """Remove and return a single queued follow-up message."""
    client = langgraph_client()
    messages = await get_queued_messages_for_thread(thread_id)
    popped: dict[str, Any] | None = None
    next_messages: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if popped is None and _message_matches(message, index, message_id):
            popped = message
        else:
            next_messages.append(message)
    if popped is None:
        return None
    await _write_queue(client, thread_id, next_messages)
    return popped


async def delete_queued_message_for_thread(thread_id: str, message_id: str) -> bool:
    """Delete one queued follow-up message."""
    return await pop_queued_message_for_thread(thread_id, message_id) is not None


async def drain_queued_messages_for_thread(thread_id: str) -> list[dict[str, Any]]:
    """Return and delete queued follow-up messages for a thread."""
    client = langgraph_client()
    messages = await get_queued_messages_for_thread(thread_id)
    if not messages:
        return []
    await client.store.delete_item(_queue_namespace(thread_id), _QUEUE_KEY)
    return messages
