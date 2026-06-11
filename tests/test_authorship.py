from __future__ import annotations

from agent.utils.authorship import (
    AGENT_BOT_EMAIL,
    AGENT_BOT_NAME,
    add_bot_coauthor_trailer,
    resolve_triggering_user_identity,
)

_BOT_TRAILER = f"Co-authored-by: {AGENT_BOT_NAME} <{AGENT_BOT_EMAIL}>"


def test_add_bot_coauthor_trailer_appends_bot() -> None:
    result = add_bot_coauthor_trailer("fix: thing")
    assert result == f"fix: thing\n\n{_BOT_TRAILER}"


def test_add_bot_coauthor_trailer_is_idempotent() -> None:
    once = add_bot_coauthor_trailer("fix: thing")
    assert add_bot_coauthor_trailer(once) == once


def test_resolve_identity_from_config_uses_session_email() -> None:
    config = {
        "configurable": {
            "source": "dashboard",
            "user_email": "mason@example.com",
            "user_name": "Mason",
        }
    }
    identity = resolve_triggering_user_identity(config)
    assert identity is not None
    assert identity.commit_name == "Mason"
    assert identity.commit_email == "mason@example.com"


def test_resolve_identity_falls_back_to_email_local_part() -> None:
    config = {"configurable": {"user_email": "dev@example.com"}}
    identity = resolve_triggering_user_identity(config)
    assert identity is not None
    assert identity.display_name == "dev"


def test_resolve_identity_returns_none_without_email() -> None:
    assert resolve_triggering_user_identity({"configurable": {}}) is None
