"""Provider-neutral user identity metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    provider: str
    subject_id: str
    email: str | None = None
    display_name: str | None = None
    tenant_id: str | None = None

    @property
    def actor_id(self) -> str:
        return f"{self.provider}:{self.subject_id}"

    @property
    def normalized_email(self) -> str | None:
        return self.email.strip().lower() if self.email and self.email.strip() else None

    def metadata(self) -> dict[str, str]:
        value = {
            "actor_id": self.actor_id,
            "auth_provider": self.provider,
        }
        if self.normalized_email:
            value["actor_email"] = self.normalized_email
        if self.display_name:
            value["actor_display_name"] = self.display_name
        if self.tenant_id:
            value["tenant_id"] = self.tenant_id
        return value


def github_user(login: str, *, email: str | None = None) -> AuthenticatedUser:
    return AuthenticatedUser(
        provider="github",
        subject_id=login.strip().lower(),
        email=email,
        display_name=login.strip() or None,
    )


def user_from_actor_id(actor_id: str, *, email: str | None = None) -> AuthenticatedUser:
    provider, sep, subject_id = actor_id.strip().partition(":")
    if not sep or not provider or not subject_id:
        return github_user(actor_id, email=email)
    return AuthenticatedUser(provider=provider, subject_id=subject_id, email=email)
