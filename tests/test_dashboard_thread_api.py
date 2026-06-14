import base64

import pytest
from agent.dashboard.options import model_supports_images
from fastapi import HTTPException

from agent.dashboard import thread_api

_TEXT_ONLY_MODEL = "on-auto-coder"
_VISION_MODEL = "on-auto-vision"


def _image() -> thread_api.DashboardImageBody:
    return thread_api.DashboardImageBody(
        base64=base64.b64encode(b"image").decode("ascii"),
        mimeType="image/png",
    )


def test_model_supports_images_marks_text_only_gateway_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", _VISION_MODEL)
    monkeypatch.setenv("MODEL_GATEWAY_IMAGE_MODELS", _VISION_MODEL)
    assert not model_supports_images(_TEXT_ONLY_MODEL)
    assert model_supports_images(_VISION_MODEL)


def test_user_message_content_rejects_images_for_text_only_model() -> None:
    with pytest.raises(HTTPException) as exc_info:
        thread_api._user_message_content("see attached", [_image()], model_id=_TEXT_ONLY_MODEL)

    assert exc_info.value.status_code == 422
    assert "does not support image input" in exc_info.value.detail


def test_user_message_content_allows_images_for_vision_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", _VISION_MODEL)
    monkeypatch.setenv("MODEL_GATEWAY_IMAGE_MODELS", _VISION_MODEL)
    content = thread_api._user_message_content("see attached", [_image()], model_id=_VISION_MODEL)

    assert isinstance(content, list)
    assert content[-1] == {"type": "text", "text": "see attached"}
    assert any(block.get("type") != "text" for block in content)


def test_langgraph_proxy_headers_include_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-key")

    headers = thread_api._langgraph_proxy_headers(accept="text/event-stream")

    assert headers["X-API-Key"] == "ls-key"
    assert headers["Accept"] == "text/event-stream"


async def test_resolve_agent_model_choice_applies_profile_before_team_default(monkeypatch) -> None:
    async def fake_team_default(role: str) -> tuple[str, str]:
        assert role == "agent"
        return _VISION_MODEL, "medium"

    monkeypatch.setattr(thread_api, "get_team_default_model", fake_team_default)

    model_id, effort = await thread_api._resolve_agent_model_choice(
        {"default_model": _TEXT_ONLY_MODEL, "reasoning_effort": "medium"},
        None,
        None,
    )

    assert (model_id, effort) == (_TEXT_ONLY_MODEL, "medium")


async def test_resolve_agent_model_choice_applies_request_before_profile(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", _VISION_MODEL)

    async def fake_team_default(role: str) -> tuple[str, str]:
        assert role == "agent"
        return _VISION_MODEL, "medium"

    monkeypatch.setattr(thread_api, "get_team_default_model", fake_team_default)

    model_id, effort = await thread_api._resolve_agent_model_choice(
        {"default_model": _TEXT_ONLY_MODEL, "reasoning_effort": "high"},
        _VISION_MODEL,
        "medium",
    )

    assert (model_id, effort) == (_VISION_MODEL, "medium")


def _new_thread_client(created: dict[str, object]) -> object:
    class FakeThreads:
        async def create(
            self, *, thread_id: str, metadata: dict[str, object], if_exists: str
        ) -> None:
            created["thread_id"] = thread_id
            created["metadata"] = dict(metadata)

        async def update(self, *, thread_id: str, metadata: dict[str, object]) -> None:
            created.setdefault("metadata", {})
            assert isinstance(created["metadata"], dict)
            created["metadata"].update(metadata)

        async def get(self, thread_id: str) -> dict[str, object]:
            return {"thread_id": thread_id, "metadata": created.get("metadata", {})}

    class FakeClient:
        threads = FakeThreads()

    return FakeClient()


def _patch_new_thread_deps(monkeypatch, *, profile: dict[str, object]) -> None:
    async def fake_profile(login: str) -> dict[str, object]:
        return dict(profile)

    async def fake_team_default(role: str) -> tuple[str, str]:
        assert role == "agent"
        return _VISION_MODEL, "medium"

    async def fake_resolve_email(login: str, prof: dict[str, object]) -> str:
        return f"{login}@example.com"

    monkeypatch.setattr(thread_api, "get_profile", fake_profile)
    monkeypatch.setattr(thread_api, "get_team_default_model", fake_team_default)
    monkeypatch.setattr(thread_api, "_resolve_run_email", fake_resolve_email)


async def test_enrich_run_start_command_creates_and_stamps_new_thread(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", _VISION_MODEL)
    created: dict[str, object] = {}
    _patch_new_thread_deps(monkeypatch, profile={})
    monkeypatch.setattr(thread_api, "langgraph_client", lambda: _new_thread_client(created))

    command = {
        "method": "run.start",
        "params": {
            "input": {"messages": [{"type": "human", "content": "Fix the flaky test"}]},
            "config": {
                "configurable": {
                    "repo": "octo/repo",
                    "agent_model_id": _VISION_MODEL,
                    "agent_effort": "medium",
                }
            },
        },
    }

    enriched = await thread_api._enrich_run_start_command(
        "new-tid",
        "octocat",
        command,
        metadata={},
        creating=True,
    )

    stamped = created["metadata"]
    assert isinstance(stamped, dict)
    assert stamped["source"] == "dashboard"
    assert stamped["owner_id"] == "octocat"
    assert stamped["title"] == "Fix the flaky test"
    assert stamped["repo_owner"] == "octo"
    assert stamped["repo_name"] == "repo"

    configurable = enriched["params"]["config"]["configurable"]
    assert configurable["actor_id"] == "octocat"
    assert configurable["source"] == "dashboard"
    assert configurable["repo"] == {"owner": "octo", "name": "repo"}
    assert configurable["agent_model_id"] == _VISION_MODEL
    assert configurable["agent_effort"] == "medium"
    # Dashboard-only creation hints must not leak into the run config.
    assert "repo_explicitly_none" not in configurable
    assert enriched["params"]["assistant_id"] == "agent"


async def test_enrich_run_start_command_rejects_images_for_resolved_text_only_model(
    monkeypatch,
) -> None:
    created: dict[str, object] = {}
    _patch_new_thread_deps(
        monkeypatch,
        profile={"default_model": _TEXT_ONLY_MODEL, "reasoning_effort": "high"},
    )
    monkeypatch.setattr(thread_api, "langgraph_client", lambda: _new_thread_client(created))

    image = _image()
    command = {
        "method": "run.start",
        "params": {
            "input": {
                "messages": [
                    {
                        "type": "human",
                        "content": [
                            {
                                "type": "image",
                                "base64": image.base64,
                                "mime_type": image.mime_type,
                            },
                            {"type": "text", "text": "see attached"},
                        ],
                    }
                ]
            },
            "config": {"configurable": {}},
        },
    }

    with pytest.raises(HTTPException) as exc_info:
        await thread_api._enrich_run_start_command(
            "new-tid",
            "octocat",
            command,
            metadata={},
            creating=True,
        )

    assert exc_info.value.status_code == 422
    assert "does not support image input" in exc_info.value.detail


def _thread_with_metadata(metadata: dict) -> dict:
    return {"thread_id": "t1", "status": "idle", "metadata": metadata}


def test_thread_summary_includes_pr_and_diff_stats() -> None:
    summary = thread_api._thread_summary(
        _thread_with_metadata(
            {
                "repo_full_name": "langchain-ai/open-swe",
                "title": "Add feature",
                "pr_number": 42,
                "pr_url": "https://github.com/langchain-ai/open-swe/pull/42",
                "pr_state": "draft",
                "pr_title": "feat: add feature",
                "branch_name": "open-swe/feature",
                "base_branch": "main",
                "diff_stats": {"files": 3, "additions": 10, "deletions": 2},
            }
        )
    )

    assert summary["pr"] == {
        "number": 42,
        "title": "feat: add feature",
        "state": "draft",
        "headRef": "open-swe/feature",
        "baseRef": "main",
        "url": "https://github.com/langchain-ai/open-swe/pull/42",
    }
    assert summary["diffStats"] == {"files": 3, "additions": 10, "deletions": 2}


def test_thread_summary_defaults_unknown_pr_state_to_open() -> None:
    summary = thread_api._thread_summary(
        _thread_with_metadata(
            {
                "pr_number": 7,
                "pr_url": "https://example.com/pull/7",
                "pr_state": "bogus",
            }
        )
    )

    assert summary["pr"]["state"] == "open"


def test_thread_summary_omits_pr_when_no_pr_metadata() -> None:
    summary = thread_api._thread_summary(_thread_with_metadata({"title": "No PR"}))

    assert "pr" not in summary
    assert "diffStats" not in summary


async def test_proxy_commands_lazily_creates_missing_thread_only_for_run_start(
    monkeypatch,
) -> None:
    class MissingThreads:
        async def get(self, thread_id: str) -> dict[str, object]:
            raise RuntimeError("thread not found")

    class MissingClient:
        threads = MissingThreads()

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: MissingClient())

    # A non-run.start command against a thread that doesn't exist yet is a 404.
    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_commands(
            "ghost", "octocat", b'{"method": "run.cancel"}'
        )
    assert exc_info.value.status_code == 404


async def test_proxy_commands_run_start_by_non_owner_is_rejected(monkeypatch) -> None:
    class OwnedThreads:
        async def get(self, thread_id: str) -> dict[str, object]:
            return {
                "thread_id": thread_id,
                "metadata": {"source": "dashboard", "owner_id": "owner"},
            }

    class OwnedClient:
        threads = OwnedThreads()

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: OwnedClient())

    # An existing thread owned by someone else is never lazily re-created — a
    # run.start from a non-owner is a 404, not a takeover.
    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_commands(
            "tid", "intruder", b'{"method": "run.start"}'
        )
    assert exc_info.value.status_code == 404


async def test_enrich_run_start_command_allowlists_client_configurable(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", _VISION_MODEL)
    updates: list[dict[str, object]] = []

    class FakeThreads:
        async def update(self, *, thread_id: str, metadata: dict[str, object]) -> None:
            assert thread_id == "tid"
            updates.append(metadata)

    class FakeClient:
        threads = FakeThreads()

    async def fake_get_profile(login: str) -> dict[str, object]:
        assert login == "octocat"
        return {}

    async def fake_resolve_email(login: str, profile: dict[str, object]) -> str:
        assert login == "octocat"
        return "octocat@example.com"

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: FakeClient())
    monkeypatch.setattr(thread_api, "get_profile", fake_get_profile)
    monkeypatch.setattr(thread_api, "_resolve_run_email", fake_resolve_email)

    command = {
        "method": "run.start",
        "params": {
            "config": {
                "configurable": {
                    "github_login": "attacker",
                    "user_email": "attacker@example.com",
                    "source": "github",
                    "repo": {"owner": "evil", "name": "repo"},
                    "agent_model_id": _VISION_MODEL,
                    "agent_effort": "medium",
                }
            }
        },
    }

    enriched = await thread_api._enrich_run_start_command(
        "tid",
        "octocat",
        command,
        metadata={
            "source": "dashboard",
            "owner_id": "octocat",
            "repo_owner": "octo",
            "repo_name": "repo",
        },
    )

    configurable = enriched["params"]["config"]["configurable"]
    assert configurable["actor_id"] == "octocat"
    assert configurable["user_email"] == "octocat@example.com"
    assert configurable["source"] == "dashboard"
    assert configurable["repo"] == {"owner": "octo", "name": "repo"}
    assert configurable["agent_model_id"] == _VISION_MODEL
    assert configurable["agent_effort"] == "medium"
    assert updates[-1]["model"] == _VISION_MODEL


async def test_enrich_run_start_command_entra_sets_provider_neutral_configurable(
    monkeypatch,
) -> None:
    class FakeThreads:
        async def update(self, *, thread_id: str, metadata: dict[str, object]) -> None:
            pass

    class FakeClient:
        threads = FakeThreads()

    async def fake_get_profile(login: str) -> dict[str, object]:
        return {}

    async def fail_resolve_email(login: str, profile: dict[str, object]) -> str:
        raise AssertionError("Entra runs must use the session email, not GitHub mapping")

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: FakeClient())
    monkeypatch.setattr(thread_api, "get_profile", fake_get_profile)
    monkeypatch.setattr(thread_api, "_resolve_run_email", fail_resolve_email)

    command = {
        "method": "run.start",
        "params": {"config": {"configurable": {}}},
    }

    enriched = await thread_api._enrich_run_start_command(
        "tid",
        "entra:user-oid",
        command,
        metadata={"source": "dashboard", "owner_id": "entra:user-oid"},
        auth_provider="entra",
        actor_id="entra:user-oid",
        email="dev@example.com",
    )

    configurable = enriched["params"]["config"]["configurable"]
    assert configurable["auth_provider"] == "entra"
    assert configurable["actor_id"] == "entra:user-oid"
    assert configurable["user_email"] == "dev@example.com"
    assert "github_login" not in configurable


async def test_proxy_commands_rejects_non_object_body(monkeypatch) -> None:
    class FakeThreads:
        async def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "tid"
            return {
                "thread_id": "tid",
                "metadata": {"source": "dashboard", "owner_id": "octocat"},
            }

    class FakeClient:
        threads = FakeThreads()

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: FakeClient())

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_commands("tid", "octocat", b"[]")

    assert exc_info.value.status_code == 400


async def test_proxy_endpoints_enforce_thread_ownership(monkeypatch) -> None:
    class FakeThreads:
        async def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "tid"
            return {
                "thread_id": "tid",
                "metadata": {"source": "dashboard", "owner_id": "owner"},
            }

    class FakeClient:
        threads = FakeThreads()

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: FakeClient())

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.get_dashboard_thread_state("tid", "intruder")
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_commands("tid", "intruder", b"{}")
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_history("tid", "intruder", b"{}")
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_run_cancel("tid", "run-1", "intruder")
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.proxy_dashboard_thread_stream_events("tid", "intruder", b"{}")
    assert exc_info.value.status_code == 404


async def test_send_dashboard_message_returns_502_when_activity_unknown(monkeypatch) -> None:
    class FakeThreads:
        async def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "tid"
            return {
                "thread_id": "tid",
                "metadata": {"source": "dashboard", "owner_id": "octocat"},
            }

    class FakeClient:
        threads = FakeThreads()

    async def unknown_activity(thread_id: str) -> None:
        assert thread_id == "tid"
        return None

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: FakeClient())
    monkeypatch.setattr(thread_api, "get_thread_active_status", unknown_activity)

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.send_dashboard_message(
            "tid",
            "octocat",
            thread_api.ThreadMessageBody(content="hello"),
        )

    assert exc_info.value.status_code == 502


class _QueuedThreads:
    def __init__(self, *, status: str = "idle") -> None:
        self.status = status
        self.metadata: dict[str, object] = {
            "source": "dashboard",
            "owner_id": "octocat",
        }
        self.updates: list[dict[str, object]] = []

    async def get(self, thread_id: str) -> dict[str, object]:
        assert thread_id == "tid"
        return {"thread_id": "tid", "status": self.status, "metadata": self.metadata}

    async def update(self, *, thread_id: str, metadata: dict[str, object]) -> None:
        assert thread_id == "tid"
        self.updates.append(metadata)
        self.metadata.update(metadata)


class _QueuedRuns:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def create(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.created.append({"args": args, "kwargs": kwargs})
        return {"run_id": "run-queued"}


class _QueuedClient:
    def __init__(self, *, status: str = "idle") -> None:
        self.threads = _QueuedThreads(status=status)
        self.runs = _QueuedRuns()


async def test_get_dashboard_queued_messages_returns_public_payload(monkeypatch) -> None:
    client = _QueuedClient()

    async def fake_get_queued(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return [
            {
                "id": "m1",
                "content": {"text": "continúa", "images": [{"type": "image"}], "secret": "x"},
            },
            {"id": "m2", "content": [{"type": "text", "text": "segundo"}, {"type": "image_url"}]},
        ]

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "get_queued_messages_for_thread", fake_get_queued)

    payload = await thread_api.get_dashboard_queued_messages("tid", "octocat")

    assert payload == {
        "count": 2,
        "messages": [
            {"id": "m1", "text": "continúa", "image_count": 1, "has_images": True},
            {"id": "m2", "text": "segundo", "image_count": 1, "has_images": True},
        ],
    }


async def test_clear_dashboard_queued_messages_drains_queue(monkeypatch) -> None:
    client = _QueuedClient()
    drained: list[str] = []

    async def fake_drain(thread_id: str) -> list[dict[str, object]]:
        drained.append(thread_id)
        return [{"content": "ignored"}]

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "drain_queued_messages_for_thread", fake_drain)

    payload = await thread_api.clear_dashboard_queued_messages("tid", "octocat")

    assert drained == ["tid"]
    assert payload == {"count": 0, "messages": []}


async def test_delete_dashboard_queued_message_deletes_one(monkeypatch) -> None:
    client = _QueuedClient()
    deleted: list[tuple[str, str]] = []

    async def fake_delete(thread_id: str, message_id: str) -> bool:
        deleted.append((thread_id, message_id))
        return True

    async def fake_get_queued(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return [{"id": "m2", "content": "queda"}]

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "delete_queued_message_for_thread", fake_delete)
    monkeypatch.setattr(thread_api, "get_queued_messages_for_thread", fake_get_queued)

    payload = await thread_api.delete_dashboard_queued_message("tid", "m1", "octocat")

    assert deleted == [("tid", "m1")]
    assert payload == {
        "count": 1,
        "messages": [{"id": "m2", "text": "queda", "image_count": 0, "has_images": False}],
    }


async def test_direct_dashboard_queued_message_marks_one_message_for_busy_thread(
    monkeypatch,
) -> None:
    client = _QueuedClient(status="busy")
    forced: list[tuple[str, str]] = []

    async def fake_force(thread_id: str, message_id: str) -> bool:
        forced.append((thread_id, message_id))
        return True

    async def fake_get_queued(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return [
            {"id": "m1", "content": "dirige esto", "force_for_active_run": True},
            {"id": "m2", "content": "queda en cola"},
        ]

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "force_queued_message_for_thread", fake_force)
    monkeypatch.setattr(thread_api, "get_queued_messages_for_thread", fake_get_queued)

    payload = await thread_api.direct_dashboard_queued_message("tid", "m1", "octocat")

    assert forced == [("tid", "m1")]
    assert payload == {
        "status": "directed",
        "run_id": None,
        "queued": {
            "count": 2,
            "messages": [
                {"id": "m1", "text": "dirige esto", "image_count": 0, "has_images": False},
                {"id": "m2", "text": "queda en cola", "image_count": 0, "has_images": False},
            ],
        },
    }
    assert client.runs.created == []


async def test_continue_dashboard_queued_messages_directs_busy_thread_queue(monkeypatch) -> None:
    client = _QueuedClient(status="busy")
    forced: list[str] = []

    async def fail_drain(thread_id: str) -> list[dict[str, object]]:
        raise AssertionError("busy threads must not drain the queue")

    async def fake_get_queued(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return [{"content": "dirige esto"}]

    async def fake_force(thread_id: str) -> bool:
        forced.append(thread_id)
        return True

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "get_queued_messages_for_thread", fake_get_queued)
    monkeypatch.setattr(thread_api, "force_queued_messages_for_thread", fake_force)
    monkeypatch.setattr(thread_api, "drain_queued_messages_for_thread", fail_drain)

    payload = await thread_api.continue_dashboard_queued_messages("tid", "octocat")

    assert forced == ["tid"]
    assert payload == {
        "status": "directed",
        "run_id": None,
        "queued": {
            "count": 1,
            "messages": [
                {"id": "queued-0", "text": "dirige esto", "image_count": 0, "has_images": False}
            ],
        },
    }
    assert client.runs.created == []


async def test_continue_dashboard_queued_messages_noops_without_queue(monkeypatch) -> None:
    client = _QueuedClient()

    async def fake_drain(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return []

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "drain_queued_messages_for_thread", fake_drain)

    payload = await thread_api.continue_dashboard_queued_messages("tid", "octocat")

    assert payload == {
        "status": "empty",
        "run_id": None,
        "queued": {"count": 0, "messages": []},
    }
    assert client.runs.created == []


async def test_continue_dashboard_queued_messages_starts_followup_run(monkeypatch) -> None:
    client = _QueuedClient()
    client.threads.metadata["latest_run_status"] = "running"

    async def fake_drain(thread_id: str) -> list[dict[str, object]]:
        assert thread_id == "tid"
        return [{"content": "primero"}, {"content": {"text": "segundo"}}]

    async def fake_profile(login: str) -> dict[str, object]:
        assert login == "octocat"
        return {}

    async def fake_resolve_email(login: str, profile: dict[str, object]) -> str:
        assert login == "octocat"
        return "octocat@example.com"

    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)
    monkeypatch.setattr(thread_api, "drain_queued_messages_for_thread", fake_drain)
    monkeypatch.setattr(thread_api, "get_profile", fake_profile)
    monkeypatch.setattr(thread_api, "_resolve_run_email", fake_resolve_email)

    payload = await thread_api.continue_dashboard_queued_messages("tid", "octocat")

    assert payload["status"] == "started"
    assert payload["run_id"] == "run-queued"
    assert len(client.runs.created) == 1
    created = client.runs.created[0]
    assert created["args"] == ("tid", "agent")
    assert created["kwargs"]["stream_mode"] == ["values", "updates", "messages-tuple"]
    assert created["kwargs"]["input"] == {
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "primero"}]},
            {"role": "user", "content": [{"type": "text", "text": "segundo"}]},
        ]
    }
    assert client.threads.updates[-1]["latest_run_id"] == "run-queued"
    assert client.threads.updates[-1]["latest_run_status"] == "pending"


class _ResumeThreads:
    def __init__(self, owner_metadata: dict[str, object]) -> None:
        self._metadata = owner_metadata

    async def get(self, thread_id: str) -> dict[str, object]:
        return {"thread_id": thread_id, "metadata": self._metadata}


class _ResumeRuns:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def create(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.created.append({"args": args, "kwargs": kwargs})
        return {"run_id": "resume-run"}


class _ResumeClient:
    def __init__(self, owner_metadata: dict[str, object]) -> None:
        self.threads = _ResumeThreads(owner_metadata)
        self.runs = _ResumeRuns()


async def test_resume_dashboard_interrupt_by_non_owner_is_rejected(monkeypatch) -> None:
    # Approving/rejecting an interrupt is a privileged decision on the approval
    # gate: a non-owner must get a 404 and the resume run must never be created.
    client = _ResumeClient({"source": "dashboard", "owner_id": "owner"})
    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)

    with pytest.raises(HTTPException) as exc_info:
        await thread_api.resume_dashboard_interrupt(
            "tid", [{"type": "approve"}], "intruder"
        )

    assert exc_info.value.status_code == 404
    assert client.runs.created == []


async def test_resume_dashboard_interrupt_owner_creates_resume_run(monkeypatch) -> None:
    client = _ResumeClient({"source": "dashboard", "owner_id": "owner"})
    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)

    result = await thread_api.resume_dashboard_interrupt(
        "tid", [{"type": "approve"}], "owner"
    )

    assert result == {"run_id": "resume-run"}
    assert len(client.runs.created) == 1
    created = client.runs.created[0]
    assert created["args"][0] == "tid"
    assert created["kwargs"]["command"] == {"resume": {"decisions": [{"type": "approve"}]}}


async def test_resume_dashboard_interrupt_matches_owner_by_email(monkeypatch) -> None:
    # Owner may be identified by email even when the login differs (e.g. Entra).
    client = _ResumeClient(
        {"source": "dashboard", "triggering_user_email": "owner@example.com"}
    )
    monkeypatch.setattr(thread_api, "langgraph_client", lambda: client)

    result = await thread_api.resume_dashboard_interrupt(
        "tid", [{"type": "reject"}], "someone-else", email="owner@example.com"
    )

    assert result == {"run_id": "resume-run"}
    assert len(client.runs.created) == 1
