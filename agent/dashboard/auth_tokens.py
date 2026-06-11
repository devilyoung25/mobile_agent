"""Provider-neutral encrypted auth token store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph_sdk import get_client

from ..encryption import encrypt_token

AUTH_TOKENS_NAMESPACE: list[str] = ["auth_tokens"]


def expires_at_from_token_response(data: dict[str, Any]) -> str | None:
    raw = data.get("expires_in")
    if not isinstance(raw, int | float) or raw <= 0:
        return None
    return (datetime.now(UTC) + timedelta(seconds=int(raw))).isoformat()


async def upsert_auth_tokens(
    *,
    actor_id: str,
    provider: str,
    tenant_id: str | None,
    email: str | None,
    token_data: dict[str, Any],
) -> None:
    access_token = token_data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return
    value: dict[str, Any] = {
        "actor_id": actor_id,
        "provider": provider,
        "tenant_id": tenant_id,
        "email": email or "",
        "encrypted_access_token": encrypt_token(access_token),
        "token_expires_at": expires_at_from_token_response(token_data),
        "scopes": token_data.get("scope") if isinstance(token_data.get("scope"), str) else "",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    refresh_token = token_data.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        value["encrypted_refresh_token"] = encrypt_token(refresh_token)
    await get_client().store.put_item(AUTH_TOKENS_NAMESPACE, actor_id, value)

