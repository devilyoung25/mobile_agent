"""Runtime configuration for the ON Model Gateway (env-driven, multi-provider).

The gateway serves several providers at once (Ollama Cloud, OpenRouter, …). Each
provider has its own base URL + key (read from the gateway's own ``.env`` so the
server's ``.env`` keeps only platform/Azure creds). A provider with no key is
simply skipped, so the catalog only shows what's actually usable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # auto-load services/model-gateway/.env so keys live next to the gateway
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover - dotenv optional
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    api_key: str
    discovery: str  # "auto" (GET /models) | "static" (fixed list)
    static_models: tuple[str, ...] = field(default_factory=tuple)


def providers() -> list[Provider]:
    """Configured providers. Only those with a key present are returned."""
    out: list[Provider] = []

    ollama_key = _env("OLLAMA_API_KEY")
    if ollama_key:
        # "auto" (default) lists the full Ollama cloud catalog; "curated" exposes
        # only GATEWAY_OLLAMA_MODELS / OLLAMA_MODELS (what this account can run).
        # NOTE: the full catalog includes subscription-locked models that 403 on
        # use; those get greyed out by the availability breaker after one attempt.
        curated = _env("GATEWAY_OLLAMA_MODELS") or _env("OLLAMA_MODELS")
        # Default to curated when a list is configured (only what the account can
        # run); set GATEWAY_OLLAMA_DISCOVERY=auto to browse the full cloud catalog.
        discovery = _env("GATEWAY_OLLAMA_DISCOVERY", "curated" if curated else "auto").lower()
        out.append(
            Provider(
                id="ollama",
                label="Ollama Cloud",
                base_url=_env("GATEWAY_OLLAMA_BASE_URL", "https://ollama.com/v1").rstrip("/"),
                api_key=ollama_key,
                discovery="static" if discovery == "curated" else "auto",
                static_models=tuple(m.strip() for m in curated.split(",") if m.strip()),
            )
        )

    openrouter_key = _env("OPENROUTER_API_KEY")
    if openrouter_key:
        models = tuple(
            m.strip() for m in _env("GATEWAY_OPENROUTER_MODELS", "openrouter/free").split(",") if m.strip()
        )
        out.append(
            Provider(
                id="openrouter",
                label="OpenRouter (free)",
                base_url=_env("GATEWAY_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
                api_key=openrouter_key,
                discovery="static",
                static_models=models,
            )
        )

    return out


def provider_by_id(provider_id: str) -> Provider | None:
    return next((p for p in providers() if p.id == provider_id), None)


def drop_params() -> set[str]:
    raw = _env("MODEL_GATEWAY_DROP_PARAMS", "reasoning_effort")
    return {p.strip() for p in raw.split(",") if p.strip()}


def inbound_api_key() -> str | None:
    return _env("MODEL_GATEWAY_API_KEY") or None


def timeout() -> float:
    return float(_env("MODEL_GATEWAY_TIMEOUT", "180"))


def cooldown_seconds() -> float:
    """Default unavailability window after a rate-limit when no Retry-After is given."""
    return float(_env("MODEL_GATEWAY_COOLDOWN", "60"))


def default_fallback() -> tuple[str, str] | None:
    """(provider_id, upstream_model) used when a requested id isn't in the catalog.

    Lets legacy aliases (e.g. ``on-auto-coder``) keep working during transition.
    """
    model = _env("MODEL_GATEWAY_DEFAULT_UPSTREAM_MODEL")
    provider = _env("MODEL_GATEWAY_DEFAULT_PROVIDER", "ollama")
    return (provider, model) if model else None
