"""Encrypted auth-token store — re-exported from the identity-entra package."""

from identity_entra.tokens import expires_at_from_token_response, upsert_auth_tokens

__all__ = ["expires_at_from_token_response", "upsert_auth_tokens"]
