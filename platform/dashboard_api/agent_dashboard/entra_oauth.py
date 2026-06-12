"""Microsoft Entra OAuth — re-exported from the identity-entra package."""

from identity_entra.oauth import (
    ENTRA_AUTHORITY_HOST,
    ENTRA_SCOPES,
    build_authorize_url,
    code_challenge_for,
    enforce_entra_allowlist,
    entra_authority,
    entra_authorize_endpoint,
    entra_client_id,
    entra_client_secret,
    entra_tenant,
    entra_token_endpoint,
    exchange_entra_code,
    identity_from_claims,
    new_code_verifier,
    token_expires_at,
    validate_entra_id_token,
)

__all__ = [
    "ENTRA_AUTHORITY_HOST",
    "ENTRA_SCOPES",
    "build_authorize_url",
    "code_challenge_for",
    "enforce_entra_allowlist",
    "entra_authority",
    "entra_authorize_endpoint",
    "entra_client_id",
    "entra_client_secret",
    "entra_tenant",
    "entra_token_endpoint",
    "exchange_entra_code",
    "identity_from_claims",
    "new_code_verifier",
    "token_expires_at",
    "validate_entra_id_token",
]
