from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import HTTPException
from identity_entra import oauth as entra_oauth


def _oct_jwk(kid: str, secret: bytes = b"secret") -> dict[str, str]:
    import base64

    key = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    return {"kty": "oct", "kid": kid, "k": key, "alg": "HS256"}


def test_build_authorize_url_uses_entra_v2_code_flow_with_pkce(monkeypatch) -> None:
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-id")
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-id")

    url = entra_oauth.build_authorize_url(
        redirect_uri="http://localhost:2024/dashboard/api/entra/callback",
        state="state",
        nonce="nonce",
        code_verifier="verifier",
    )

    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == "/tenant-id/oauth2/v2.0/authorize"
    assert q["client_id"] == ["client-id"]
    assert q["response_type"] == ["code"]
    assert q["response_mode"] == ["query"]
    assert q["redirect_uri"] == ["http://localhost:2024/dashboard/api/entra/callback"]
    assert q["scope"] == [
        "openid profile email offline_access "
        "499b84ac-1321-427f-aa17-267ca6975798/user_impersonation"
    ]
    assert q["state"] == ["state"]
    assert q["nonce"] == ["nonce"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"][0] == entra_oauth.code_challenge_for("verifier")


def test_entra_allowlist_accepts_configured_tenant_and_domain(monkeypatch) -> None:
    monkeypatch.setenv("ENTRA_ALLOWED_TENANTS", "tenant-a")
    monkeypatch.setenv("ENTRA_ALLOWED_DOMAINS", "example.com")

    entra_oauth.enforce_entra_allowlist(
        {"tid": "tenant-a", "preferred_username": "Dev@Example.COM"}
    )


def test_entra_allowlist_rejects_unconfigured_tenant(monkeypatch) -> None:
    monkeypatch.setenv("ENTRA_ALLOWED_TENANTS", "tenant-a")
    monkeypatch.delenv("ENTRA_ALLOWED_DOMAINS", raising=False)

    with pytest.raises(HTTPException) as exc:
        entra_oauth.enforce_entra_allowlist({"tid": "tenant-b", "email": "dev@example.com"})

    assert exc.value.status_code == 403


def test_entra_allowlist_rejects_unconfigured_domain(monkeypatch) -> None:
    monkeypatch.delenv("ENTRA_ALLOWED_TENANTS", raising=False)
    monkeypatch.setenv("ENTRA_ALLOWED_DOMAINS", "example.com")

    with pytest.raises(HTTPException) as exc:
        entra_oauth.enforce_entra_allowlist({"tid": "tenant-a", "email": "dev@other.com"})

    assert exc.value.status_code == 403


def test_identity_from_claims_uses_oid_and_tenant() -> None:
    identity = entra_oauth.identity_from_claims(
        {
            "oid": "user-oid",
            "tid": "tenant-id",
            "preferred_username": "dev@example.com",
            "name": "Dev User",
        }
    )

    assert identity.actor_id == "entra:user-oid"
    assert identity.provider == "entra"
    assert identity.tenant_id == "tenant-id"
    assert identity.normalized_email == "dev@example.com"
    assert identity.display_name == "Dev User"


def test_signing_key_from_jwks_selects_matching_kid() -> None:
    token = jwt.encode({"tid": "tenant-id"}, "secret", algorithm="HS256", headers={"kid": "k2"})

    key = entra_oauth._signing_key_from_jwks(
        token,
        {"keys": [_oct_jwk("k1", b"wrong"), _oct_jwk("k2")]},
    )

    assert key == b"secret"


@pytest.mark.asyncio
async def test_validate_entra_id_token_fetches_jwks_without_sync_jwk_client(monkeypatch) -> None:
    token = jwt.encode({"tid": "tenant-id"}, "secret", algorithm="HS256", headers={"kid": "k1"})

    async def fake_openid_config(tenant_id: str) -> dict[str, str]:
        assert tenant_id == "tenant-id"
        return {
            "issuer": "https://login.microsoftonline.com/tenant-id/v2.0",
            "jwks_uri": "https://login.microsoftonline.com/tenant-id/discovery/keys",
        }

    async def fake_jwks(jwks_uri: str) -> dict[str, object]:
        assert jwks_uri == "https://login.microsoftonline.com/tenant-id/discovery/keys"
        return {"keys": [_oct_jwk("k1")]}

    def fake_decode(id_token: str, key: object = "", **kwargs: object) -> dict[str, object]:
        if kwargs.get("options") == {"verify_signature": False}:
            return {"tid": "tenant-id"}
        assert id_token == token
        assert key == b"secret"
        assert kwargs["algorithms"] == ["RS256"]
        return {"tid": "tenant-id", "nonce": "nonce"}

    monkeypatch.setattr(entra_oauth, "_openid_config_for_tenant", fake_openid_config)
    monkeypatch.setattr(entra_oauth, "_jwks_for_uri", fake_jwks)
    monkeypatch.setattr(entra_oauth, "entra_client_id", lambda: "client-id")
    monkeypatch.setattr(entra_oauth.jwt, "decode", fake_decode)

    claims = await entra_oauth.validate_entra_id_token(token, nonce="nonce")

    assert claims == {"tid": "tenant-id", "nonce": "nonce"}
