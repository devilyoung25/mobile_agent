"""Tests for the brand-neutral directed message-queue middleware."""

from unittest.mock import MagicMock, patch

from on_core.middleware.check_message_queue import check_message_queue_before_model

_MODULE = "on_core.middleware.check_message_queue"


class _QueuedItem:
    def __init__(self, value: dict) -> None:
        self.value = value


class _FakeStore:
    """Minimal async Store double recording writes/deletes."""

    def __init__(self, value: dict | None = None) -> None:
        self._value = value
        self.deleted: list[tuple[tuple[str, ...], str]] = []
        self.writes: list[tuple[tuple[str, ...], str, dict]] = []

    async def aget(self, namespace: tuple[str, ...], key: str) -> _QueuedItem | None:
        if self._value is None:
            return None
        return _QueuedItem(self._value)

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        self.deleted.append((namespace, key))
        self._value = None

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        self.writes.append((namespace, key, value))
        self._value = value


def _patch_context(store: _FakeStore, thread_id: str | None = "thread-1"):
    configurable = {"thread_id": thread_id} if thread_id is not None else {}
    return (
        patch(f"{_MODULE}.get_config", return_value={"configurable": configurable}),
        patch(f"{_MODULE}.get_store", return_value=store),
    )


async def test_injects_dict_text_message_and_drains_queue() -> None:
    store = _FakeStore(
        {
            "messages": [
                {
                    "content": {"text": "continúa en el panel", "source": "dashboard"},
                    "force_for_active_run": True,
                }
            ],
        }
    )
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result is not None
    message = result["messages"][0]
    assert message["role"] == "user"
    # Brand-neutral: the queued text is injected as-is, no handoff marker prepended.
    assert message["content"] == [{"type": "text", "text": "continúa en el panel"}]
    assert store.deleted == [(("queue", "thread-1"), "pending_messages")]


async def test_injects_plain_string_content() -> None:
    store = _FakeStore(
        {"messages": [{"content": "hola mid-run", "force_for_active_run": True}]}
    )
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result["messages"][0]["content"] == [{"type": "text", "text": "hola mid-run"}]
    assert store.deleted == [(("queue", "thread-1"), "pending_messages")]


async def test_preserves_image_blocks_from_dict_payload() -> None:
    image_block = {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}}
    store = _FakeStore(
        {
            "messages": [
                {
                    "content": {"text": "mira esto", "images": [image_block]},
                    "force_for_active_run": True,
                }
            ],
        }
    )
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    content = result["messages"][0]["content"]
    assert {"type": "text", "text": "mira esto"} in content
    assert image_block in content


async def test_concatenates_multiple_queued_messages_fifo() -> None:
    store = _FakeStore(
        {
            "messages": [
                {"content": "primero", "force_for_active_run": True},
                {"content": "segundo", "force_for_active_run": True},
            ],
        }
    )
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result["messages"][0]["content"] == [
        {"type": "text", "text": "primero"},
        {"type": "text", "text": "segundo"},
    ]


async def test_no_queue_returns_none_without_delete() -> None:
    store = _FakeStore(None)
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result is None
    assert store.deleted == []


async def test_empty_messages_drains_but_injects_nothing() -> None:
    store = _FakeStore({"force_for_active_run": True, "messages": []})
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result is None
    assert store.deleted == [(("queue", "thread-1"), "pending_messages")]


async def test_no_thread_id_returns_none() -> None:
    store = _FakeStore(
        {"messages": [{"content": "x", "force_for_active_run": True}]}
    )
    cfg, st = _patch_context(store, thread_id=None)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result is None
    assert store.deleted == []


async def test_regular_queued_messages_wait_for_run_completion() -> None:
    store = _FakeStore({"messages": [{"content": "espera al final"}]})
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result is None
    assert store.deleted == []


async def test_directed_message_leaves_regular_messages_queued() -> None:
    store = _FakeStore(
        {
            "messages": [
                {"id": "m1", "content": "dirigido", "force_for_active_run": True},
                {"id": "m2", "content": "espera al final"},
            ],
        }
    )
    cfg, st = _patch_context(store)
    with cfg, st:
        result = await check_message_queue_before_model.abefore_model({}, MagicMock())

    assert result["messages"][0]["content"] == [{"type": "text", "text": "dirigido"}]
    assert store.deleted == []
    assert store.writes == [
        (
            ("queue", "thread-1"),
            "pending_messages",
            {"messages": [{"id": "m2", "content": "espera al final"}]},
        )
    ]
