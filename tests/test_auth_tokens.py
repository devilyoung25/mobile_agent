from unittest.mock import AsyncMock, patch

from agent.dashboard.auth_tokens import upsert_auth_tokens


async def test_upsert_auth_tokens_encrypts_provider_tokens() -> None:
    store = AsyncMock()
    client = AsyncMock()
    client.store = store

    with (
        patch("agent.dashboard.auth_tokens.get_client", return_value=client),
        patch("agent.dashboard.auth_tokens.encrypt_token", side_effect=lambda token: f"enc:{token}"),
    ):
        await upsert_auth_tokens(
            actor_id="entra:user-oid",
            provider="entra",
            tenant_id="tenant-id",
            email="dev@example.com",
            token_data={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "openid profile",
            },
        )

    store.put_item.assert_awaited_once()
    namespace, key, value = store.put_item.await_args.args
    assert namespace == ["auth_tokens"]
    assert key == "entra:user-oid"
    assert value["encrypted_access_token"] == "enc:access"
    assert value["encrypted_refresh_token"] == "enc:refresh"
    assert value["provider"] == "entra"
    assert value["tenant_id"] == "tenant-id"
    assert value["scopes"] == "openid profile"

