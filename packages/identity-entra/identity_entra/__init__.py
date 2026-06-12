"""Microsoft Entra identity provider for ON Mobile Agent."""

from .encryption import EncryptionKeyMissingError, decrypt_token, encrypt_token
from .models import AuthenticatedUser, user_from_actor_id
from .oauth import (
    build_authorize_url,
    code_challenge_for,
    enforce_entra_allowlist,
    entra_authority,
    entra_client_id,
    exchange_entra_code,
    identity_from_claims,
    new_code_verifier,
    validate_entra_id_token,
)
from .tokens import expires_at_from_token_response, upsert_auth_tokens

__all__ = [
    "AuthenticatedUser",
    "EncryptionKeyMissingError",
    "build_authorize_url",
    "code_challenge_for",
    "decrypt_token",
    "encrypt_token",
    "enforce_entra_allowlist",
    "entra_authority",
    "entra_client_id",
    "exchange_entra_code",
    "expires_at_from_token_response",
    "identity_from_claims",
    "new_code_verifier",
    "upsert_auth_tokens",
    "user_from_actor_id",
    "validate_entra_id_token",
]
