"""Provider-neutral encrypted auth token store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph_sdk import get_client

from .encryption import encrypt_token
from .oauth import AZURE_DEVOPS_USER_IMPERSONATION_SCOPE

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


# Azure DevOps delegated scope. Using ``user_impersonation`` (not ``.default``)
# means the silent refresh redeems the same incremental, user-consented scope
# the user granted at login — no admin consent required. A token minted with
# this scope authenticates against https://mcp.dev.azure.com and the Azure
# DevOps REST APIs.
AZURE_DEVOPS_SCOPE = AZURE_DEVOPS_USER_IMPERSONATION_SCOPE


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _get_token_record(actor_id: str) -> dict[str, Any] | None:
    import httpx

    try:
        item = await get_client().store.get_item(AUTH_TOKENS_NAMESPACE, actor_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
    if item is None:
        return None
    value = item.get("value") if isinstance(item, dict) else getattr(item, "value", None)
    return value if isinstance(value, dict) else None


async def get_azure_devops_access_token(actor_id: str) -> str | None:
    """Mint (or reuse) an Azure DevOps-scoped access token for the actor.

    Uses the stored Entra refresh token to request a token for the Azure
    DevOps resource. The minted token is cached on the actor's token record
    until shortly before expiry. Returns ``None`` when the actor has no
    stored refresh token or the tenant has not consented to the Azure DevOps
    delegated permission — callers degrade to no ADO tools.
    """
    import logging

    import httpx

    from .encryption import decrypt_token
    from .oauth import entra_client_id, entra_client_secret, entra_token_endpoint

    logger = logging.getLogger(__name__)

    record = await _get_token_record(actor_id)
    if not record:
        return None

    cached = record.get("encrypted_ado_access_token")
    cached_expiry = _parse_iso(record.get("ado_token_expires_at"))
    if (
        isinstance(cached, str)
        and cached
        and cached_expiry is not None
        and cached_expiry - timedelta(minutes=5) > datetime.now(UTC)
    ):
        return decrypt_token(cached)

    encrypted_refresh = record.get("encrypted_refresh_token")
    if not isinstance(encrypted_refresh, str) or not encrypted_refresh:
        return None

    async with httpx.AsyncClient(timeout=15.0) as http:
        response = await http.post(
            entra_token_endpoint(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": decrypt_token(encrypted_refresh),
                "client_id": entra_client_id(),
                "client_secret": entra_client_secret(),
                "scope": f"{AZURE_DEVOPS_SCOPE} offline_access",
            },
        )
    if response.status_code != 200:
        logger.warning(
            "Azure DevOps token mint failed for %s: %s %s",
            actor_id,
            response.status_code,
            response.text[:300],
        )
        return None
    data = response.json()
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None

    record["encrypted_ado_access_token"] = encrypt_token(access_token)
    record["ado_token_expires_at"] = expires_at_from_token_response(data)
    new_refresh = data.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        record["encrypted_refresh_token"] = encrypt_token(new_refresh)
    record["updated_at"] = datetime.now(UTC).isoformat()
    await get_client().store.put_item(AUTH_TOKENS_NAMESPACE, actor_id, record)
    return access_token
