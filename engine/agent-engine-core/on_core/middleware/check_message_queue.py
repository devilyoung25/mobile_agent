"""Before-model middleware that injects explicitly directed follow-up messages.

When a user sends a message while a run is still active, the platform queues it
in the LangGraph store (namespace ``("queue", thread_id)`` key
``pending_messages``). Normal queued messages wait for the current run to finish.
This middleware only drains the queue when the dashboard marks it with
``force_for_active_run=True`` (the explicit "Dirigir" action), so mid-run
redirection is intentional instead of surprising.

Brand-free: it only reads the generic queue namespace and supports plain text,
pre-formed content blocks, and ``{text, images}`` payloads. It does not fetch
remote image URLs (that would couple the engine to the composition layer) and
carries no Slack/Linear/GitHub specifics.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentState, before_model
from langgraph.config import get_config, get_store
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _blocks_from_content(content: Any) -> list[dict[str, Any]]:
    """Normalize one queued message's ``content`` into a list of content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, dict):
        blocks: list[dict[str, Any]] = []
        text = content.get("text")
        if isinstance(text, str) and text:
            blocks.append({"type": "text", "text": text})
        images = content.get("images")
        if isinstance(images, list):
            blocks.extend(image for image in images if isinstance(image, dict))
        return blocks
    return []


@before_model(state_schema=AgentState)
async def check_message_queue_before_model(
    state: AgentState,  # noqa: ARG001
    runtime: Runtime,  # noqa: ARG001
) -> dict[str, Any] | None:
    """Drain queued follow-up messages for this thread and inject them (FIFO)."""
    try:
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None

        try:
            store = get_store()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not get store from context: %s", exc)
            return None
        if store is None:
            return None

        namespace = ("queue", thread_id)
        try:
            queued_item = await store.aget(namespace, "pending_messages")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read queued messages: %s", exc)
            return None
        if queued_item is None:
            return None

        queued_messages = queued_item.value.get("messages", [])
        if not isinstance(queued_messages, list):
            return None
        if not queued_messages:
            await store.adelete(namespace, "pending_messages")
            return None

        force_all = queued_item.value.get("force_for_active_run") is True
        forced_messages: list[dict[str, Any]] = []
        remaining_messages: list[dict[str, Any]] = []
        for message in queued_messages:
            if not isinstance(message, dict):
                continue
            if force_all or message.get("force_for_active_run") is True:
                forced_messages.append(message)
            else:
                remaining_messages.append(message)

        if not forced_messages:
            return None

        # Update early so a re-run of this middleware can't double-inject the
        # directed messages, while normal queued messages keep waiting.
        if remaining_messages:
            await store.aput(namespace, "pending_messages", {"messages": remaining_messages})
        else:
            await store.adelete(namespace, "pending_messages")
        if not forced_messages:
            return None

        logger.info(
            "Found %d directed queued message(s) for thread %s, injecting into state",
            len(forced_messages),
            thread_id,
        )

        content_blocks: list[dict[str, Any]] = []
        for msg in forced_messages:
            content_blocks.extend(_blocks_from_content(msg.get("content")))
        if not content_blocks:
            return None

        injected: dict[str, Any] = {"role": "user", "content": content_blocks}
        # Preserve the queued message id on a single directed message so the
        # dashboard's optimistic user bubble dedupes against the hydrated state
        # message (same id) instead of rendering the directed message twice.
        if len(forced_messages) == 1:
            forced_id = forced_messages[0].get("id")
            if isinstance(forced_id, str) and forced_id:
                injected["id"] = forced_id
        return {"messages": [injected]}
    except Exception:
        logger.exception("Error in check_message_queue_before_model")
        return None
