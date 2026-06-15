"""Model catalog across providers + reactive availability (circuit breaker).

The catalog is built by discovering each provider's models (auto via ``GET
/models`` or a static list) and cached briefly. Availability is reactive: a model
that returns 429/rate-limit upstream is marked unavailable for a cooldown window
(honoring ``Retry-After``) and reported as such in ``/v1/models`` so the UI can
grey it out; it auto-recovers when the window passes or a request later succeeds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from . import config

_DEFAULT_EFFORTS: tuple[str, ...] = ("low", "medium", "high")

# model_id -> monotonic timestamp until which it is considered unavailable
_unavailable: dict[str, float] = {}

_cache: list["CatalogModel"] | None = None
_cache_at: float = 0.0
_CACHE_TTL = 300.0


@dataclass(frozen=True)
class CatalogModel:
    id: str
    provider: str
    upstream_model: str
    label: str
    max_input_tokens: int = 256_000
    max_output_tokens: int = 64_000
    supports_images: bool = False
    efforts: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_EFFORTS)
    default_effort: str = "medium"

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "object": "model",
            "provider": self.provider,
            "label": self.label,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "supports_images": self.supports_images,
            "efforts": list(self.efforts),
            "default_effort": self.default_effort,
            "available": is_available(self.id),
        }


async def _discover(provider: config.Provider) -> list[str]:
    if provider.discovery == "static":
        return list(provider.static_models)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{provider.base_url}/models",
                headers={"Authorization": f"Bearer {provider.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except (httpx.HTTPError, ValueError):
        return []
    return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]


async def build_catalog(force: bool = False) -> list[CatalogModel]:
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache is not None and now - _cache_at < _CACHE_TTL:
        return _cache
    models: list[CatalogModel] = []
    seen: set[str] = set()
    for provider in config.providers():
        for model_id in await _discover(provider):
            if model_id in seen:
                continue
            seen.add(model_id)
            models.append(
                CatalogModel(
                    id=model_id,
                    provider=provider.id,
                    upstream_model=model_id,
                    label=model_id,
                )
            )
    _cache = models
    _cache_at = now
    return models


async def lookup(model_id: str) -> CatalogModel | None:
    return next((m for m in await build_catalog() if m.id == model_id), None)


def is_available(model_id: str) -> bool:
    expires = _unavailable.get(model_id)
    if expires is None:
        return True
    if time.monotonic() >= expires:
        _unavailable.pop(model_id, None)
        return True
    return False


def mark_unavailable(model_id: str, retry_after: float | None = None) -> None:
    _unavailable[model_id] = time.monotonic() + (retry_after or config.cooldown_seconds())


def mark_available(model_id: str) -> None:
    _unavailable.pop(model_id, None)


def reset_state() -> None:
    """Test helper: clear cache + availability."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0
    _unavailable.clear()
