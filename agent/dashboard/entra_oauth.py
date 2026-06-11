"""Microsoft Entra authorization-code login helpers."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException

from ..identity.models import AuthenticatedUser

ENTRA_AUTHORITY_HOST = "https://login.microsoftonline.com"
ENTRA_SCOPES = "openid profile email offline_access"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def entra_client_id() -> str:
    value = _env("ENTRA_CLIENT_ID")
    if not value:
        raise HTTPException(500, "ENTRA_CLIENT_ID not configured")
    return value


def entra_client_secret() -> str:
    value = _env("ENTRA_CLIENT_SECRET")
    if not value:
        raise HTTPException(500, "ENTRA_CLIENT_SECRET not configured")
    return value


def entra_tenant() -> str:
    return _env("ENTRA_TENANT_ID") or "organizations"


def entra_authority() -> str:
    explicit = _env("ENTRA_AUTHORITY")
    if explicit:
        return explicit.rstrip("/")
    return f"{ENTRA_AUTHORITY_HOST}/{entra_tenant()}"


def entra_authorize_endpoint() -> str:
    return f"{entra_authority()}/oauth2/v2.0/authorize"


def entra_token_endpoint() -> str:
    return f"{entra_authority()}/oauth2/v2.0/token"


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_verifier: str,
) -> str:
    query = urlencode(
        {
            "client_id": entra_client_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": ENTRA_SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge_for(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{entra_authorize_endpoint()}?{query}"


async def exchange_entra_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            entra_token_endpoint(),
            data={
                "client_id": entra_client_id(),
                "client_secret": entra_client_secret(),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "scope": ENTRA_SCOPES,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise HTTPException(400, f"entra token exchange failed: {resp.text}")
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("id_token"), str):
        raise HTTPException(400, "entra token exchange missing id_token")
    return data


async def _openid_config_for_tenant(tenant_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ENTRA_AUTHORITY_HOST}/{tenant_id}/v2.0/.well-known/openid-configuration"
        )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


async def _jwks_for_uri(jwks_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_uri)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _signing_key_from_jwks(id_token: str, jwks: dict[str, Any]) -> Any:
    headers = jwt.get_unverified_header(id_token)
    token_kid = headers.get("kid")
    keys = jwks.get("keys")
    if not isinstance(token_kid, str) or not isinstance(keys, list):
        raise HTTPException(502, "entra signing keys are incomplete")
    for key_data in keys:
        if isinstance(key_data, dict) and key_data.get("kid") == token_kid:
            return jwt.PyJWK.from_dict(key_data).key
    raise HTTPException(401, "entra signing key not found")


async def validate_entra_id_token(id_token: str, *, nonce: str) -> dict[str, Any]:
    unverified = jwt.decode(id_token, options={"verify_signature": False})
    tenant_id = unverified.get("tid")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(400, "entra id_token missing tenant")
    config = await _openid_config_for_tenant(tenant_id)
    jwks_uri = config.get("jwks_uri")
    issuer = config.get("issuer") or f"{ENTRA_AUTHORITY_HOST}/{tenant_id}/v2.0"
    if not isinstance(jwks_uri, str) or not isinstance(issuer, str):
        raise HTTPException(502, "entra openid configuration is incomplete")
    jwks = await _jwks_for_uri(jwks_uri)
    signing_key = _signing_key_from_jwks(id_token, jwks)
    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=entra_client_id(),
            issuer=issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid entra id_token: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise HTTPException(400, "entra nonce mismatch")
    return claims


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in _env(name).split(",") if item.strip())


def _allowed_tenants() -> frozenset[str]:
    configured = _csv_env("ENTRA_ALLOWED_TENANTS")
    tenant = _env("ENTRA_TENANT_ID")
    if tenant and tenant not in {"common", "organizations", "consumers"}:
        configured = configured | {tenant.lower()}
    return configured


def _allowed_domains() -> frozenset[str]:
    return _csv_env("ENTRA_ALLOWED_DOMAINS")


def _claim_email(claims: dict[str, Any]) -> str | None:
    for key in ("email", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def enforce_entra_allowlist(claims: dict[str, Any]) -> None:
    tenant_id = claims.get("tid")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(400, "entra id_token missing tenant")
    tenants = _allowed_tenants()
    if tenants and tenant_id.lower() not in tenants:
        raise HTTPException(403, "tenant is not authorized")

    domains = _allowed_domains()
    email = _claim_email(claims)
    if domains:
        if not email or "@" not in email:
            raise HTTPException(403, "signed-in account has no email domain to validate")
        domain = email.rsplit("@", 1)[1].lower()
        if domain not in domains:
            raise HTTPException(403, "email domain is not authorized")


def identity_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    oid = claims.get("oid")
    tid = claims.get("tid")
    if not isinstance(oid, str) or not oid:
        raise HTTPException(400, "entra id_token missing object id")
    if not isinstance(tid, str) or not tid:
        raise HTTPException(400, "entra id_token missing tenant")
    name = claims.get("name") if isinstance(claims.get("name"), str) else None
    return AuthenticatedUser(
        provider="entra",
        subject_id=oid,
        email=_claim_email(claims),
        display_name=name,
        tenant_id=tid,
    )


def token_expires_at(claims: dict[str, Any]) -> str | None:
    exp = claims.get("exp")
    if isinstance(exp, int | float):
        return datetime.fromtimestamp(exp, tz=UTC).isoformat()
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()
