from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from agent.dashboard import routes


@pytest.mark.asyncio
async def test_entra_callback_creates_internal_session_and_stores_tokens(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_JWT_SECRET", "secret")
    monkeypatch.setenv("DASHBOARD_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("DASHBOARD_API_BASE_URL", "http://localhost:2024")

    nonce = "nonce"
    state = routes.issue_state(
        redirect_to="http://localhost:5173",
        nonce_hash=routes.hash_state_nonce(nonce),
    )
    request = type(
        "Request",
        (),
        {"cookies": {routes.ENTRA_STATE_COOKIE_NAME: nonce, routes.ENTRA_PKCE_COOKIE_NAME: "pkce"}},
    )()

    token_data = {
        "access_token": "access",
        "refresh_token": "refresh",
        "id_token": "id-token",
        "expires_in": 3600,
    }
    claims = {
        "oid": "user-oid",
        "tid": "tenant-id",
        "preferred_username": "dev@example.com",
        "name": "Dev User",
    }

    with (
        patch("agent.dashboard.routes.exchange_entra_code", new_callable=AsyncMock) as exchange,
        patch("agent.dashboard.routes.validate_entra_id_token", new_callable=AsyncMock) as validate,
        patch("agent.dashboard.routes.upsert_auth_tokens", new_callable=AsyncMock) as upsert,
    ):
        exchange.return_value = token_data
        validate.return_value = claims
        response = await routes.entra_callback(request, code="code", state=state)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:5173"
    exchange.assert_awaited_once()
    validate.assert_awaited_once_with("id-token", nonce=nonce)
    upsert.assert_awaited_once()
    assert upsert.await_args.kwargs["actor_id"] == "entra:user-oid"


@pytest.mark.asyncio
async def test_entra_callback_rejects_missing_pkce(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_JWT_SECRET", "secret")
    nonce = "nonce"
    state = routes.issue_state(redirect_to="", nonce_hash=routes.hash_state_nonce(nonce))
    request = type("Request", (), {"cookies": {routes.ENTRA_STATE_COOKIE_NAME: nonce}})()

    with pytest.raises(HTTPException) as exc:
        await routes.entra_callback(request, code="code", state=state)

    assert exc.value.status_code == 400

