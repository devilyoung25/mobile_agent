"""Token encryption — re-exported from the identity-entra package."""

from identity_entra.encryption import (
    EncryptionKeyMissingError,
    decrypt_token,
    encrypt_token,
)

__all__ = ["EncryptionKeyMissingError", "decrypt_token", "encrypt_token"]
