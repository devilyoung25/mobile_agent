"""Model capability discovery from ON Model Gateway.

The gateway is the single source of truth for per-model capabilities. It exposes
them by extending the standard OpenAI ``GET /v1/models`` response with extra
fields (ignored by standard OpenAI clients):

```json
{ "object": "list", "data": [
  { "id": "on-auto-coder", "object": "model", "owned_by": "on-model-gateway",
    "label": "ON Auto Coder",
    "max_input_tokens": 200000, "max_output_tokens": 64000,
    "supports_images": false,
    "efforts": ["medium", "high"], "default_effort": "medium" }
] }
```

The agent derives the dashboard catalog, the summarization/context window
(``max_input_tokens`` -> model profile), reasoning effort, image support, and the
output token cap from this metadata — so none of it is hardcoded or duplicated.

Concurrency contract: all network IO is async (``fetch_models``/``get_models``);
``snapshot()`` is pure and never blocks, so it is safe to call from sync code and
from inside the event loop (avoiding the blockbuster guard). Environment variables
remain a fallback for when the gateway is unreachable or has not yet implemented
the extra fields.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from .kwargs import (
    DEFAULT_GATEWAY_EFFORT,
    DEFAULT_GATEWAY_MODEL,
    gateway_api_key,
    gateway_base_url,
)

logger = logging.getLogger(__name__)

_DEFAULT_EFFORTS: tuple[str, ...] = ("medium",)
_DEFAULT_METADATA_TTL = 120.0
_DEFAULT_FETCH_TIMEOUT = 5.0


@dataclass(frozen=True)
class GatewayModel:
    """Capabilities of one logical gateway model."""

    id: str
    label: str
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_images: bool
    efforts: tuple[str, ...]
    default_effort: str

    def to_profile(self) -> dict[str, object] | None:
        """Build a langchain ``ModelProfile`` dict from these capabilities.

        ``max_input_tokens`` is what ``deepagents`` reads to compute the
        summarization trigger (fraction of the real context window). When it is
        unknown the profile omits it and deepagents falls back to its fixed
        conservative default.
        """
        profile: dict[str, object] = {
            "image_inputs": self.supports_images,
            "image_url_inputs": self.supports_images,
        }
        if self.max_input_tokens is not None:
            profile["max_input_tokens"] = self.max_input_tokens
        if self.max_output_tokens is not None:
            profile["max_output_tokens"] = self.max_output_tokens
        return profile


# --------------------------------------------------------------------------- #
# Env parsing (fallback + per-field defaults). Single home for MODEL_GATEWAY_*  #
# catalog vars so the registry never parses env directly.                       #
# --------------------------------------------------------------------------- #
def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _int_env(name: str) -> int | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s must be an integer; ignoring %r", name, raw)
        return None


def _env_key_suffix(model_id: str) -> str:
    return model_id.upper().replace("-", "_").replace(".", "_").replace(":", "_")


def _label_overrides() -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in _csv_env("MODEL_GATEWAY_MODEL_LABELS"):
        model, sep, label = item.partition("=")
        if sep and model.strip() and label.strip():
            labels[model.strip()] = label.strip()
    return labels


def _label_for(model_id: str) -> str:
    return _label_overrides().get(model_id, model_id)


def _efforts_for(model_id: str) -> tuple[str, ...]:
    suffix = _env_key_suffix(model_id)
    efforts = (
        _csv_env(f"MODEL_GATEWAY_EFFORTS_{suffix}")
        or _csv_env("MODEL_GATEWAY_EFFORTS")
        or list(_DEFAULT_EFFORTS)
    )
    return tuple(efforts)


def _default_effort_for(efforts: tuple[str, ...]) -> str:
    preferred = _env("MODEL_GATEWAY_DEFAULT_EFFORT")
    if preferred and preferred in efforts:
        return preferred
    if DEFAULT_GATEWAY_EFFORT in efforts:
        return DEFAULT_GATEWAY_EFFORT
    return efforts[0] if efforts else DEFAULT_GATEWAY_EFFORT


def _image_models() -> set[str]:
    return set(_csv_env("MODEL_GATEWAY_IMAGE_MODELS"))


def _max_input_for(model_id: str) -> int | None:
    return _int_env(f"MODEL_GATEWAY_MAX_INPUT_TOKENS_{_env_key_suffix(model_id)}") or _int_env(
        "MODEL_GATEWAY_MAX_INPUT_TOKENS"
    )


def _max_output_for(model_id: str) -> int | None:
    return _int_env(f"MODEL_GATEWAY_MAX_OUTPUT_TOKENS_{_env_key_suffix(model_id)}") or _int_env(
        "MODEL_GATEWAY_MAX_OUTPUT_TOKENS"
    )


def _configured_model_ids() -> list[str]:
    models = _csv_env("MODEL_GATEWAY_MODELS")
    default_model = _env("MODEL_GATEWAY_MODEL") or DEFAULT_GATEWAY_MODEL
    if default_model:
        models.insert(0, default_model)
    subagent_model = _env("MODEL_GATEWAY_SUBAGENT_MODEL")
    if subagent_model:
        models.append(subagent_model)

    seen: set[str] = set()
    unique: list[str] = []
    for model in models or [DEFAULT_GATEWAY_MODEL]:
        if model and model not in seen:
            unique.append(model)
            seen.add(model)
    return unique


def _model_from_env(model_id: str) -> GatewayModel:
    efforts = _efforts_for(model_id)
    return GatewayModel(
        id=model_id,
        label=_label_for(model_id),
        max_input_tokens=_max_input_for(model_id),
        max_output_tokens=_max_output_for(model_id),
        supports_images=model_id in _image_models(),
        efforts=efforts,
        default_effort=_default_effort_for(efforts),
    )


def _env_fallback() -> list[GatewayModel]:
    return [_model_from_env(model_id) for model_id in _configured_model_ids()]


def _parse_model(item: dict[str, object]) -> GatewayModel | None:
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    model_id = raw_id.strip()

    label = item.get("label")
    label = label.strip() if isinstance(label, str) and label.strip() else _label_for(model_id)

    max_input = item.get("max_input_tokens")
    max_input = max_input if isinstance(max_input, int) else _max_input_for(model_id)

    max_output = item.get("max_output_tokens")
    max_output = max_output if isinstance(max_output, int) else _max_output_for(model_id)

    if "supports_images" in item:
        supports_images = bool(item.get("supports_images"))
    else:
        supports_images = model_id in _image_models()

    raw_efforts = item.get("efforts")
    if isinstance(raw_efforts, list) and raw_efforts:
        efforts = tuple(str(e).strip() for e in raw_efforts if str(e).strip())
    else:
        efforts = _efforts_for(model_id)
    efforts = efforts or _DEFAULT_EFFORTS

    raw_default = item.get("default_effort")
    if isinstance(raw_default, str) and raw_default.strip() in efforts:
        default_effort = raw_default.strip()
    else:
        default_effort = _default_effort_for(efforts)

    return GatewayModel(
        id=model_id,
        label=label,
        max_input_tokens=max_input,
        max_output_tokens=max_output,
        supports_images=supports_images,
        efforts=efforts,
        default_effort=default_effort,
    )


# --------------------------------------------------------------------------- #
# Async fetch + TTL cache                                                       #
# --------------------------------------------------------------------------- #
_cache: list[GatewayModel] | None = None
_cache_at: float = 0.0
_lock = asyncio.Lock()


def _ttl() -> float:
    raw = _env("MODEL_GATEWAY_METADATA_TTL")
    if not raw:
        return _DEFAULT_METADATA_TTL
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_METADATA_TTL


def _timeout() -> float:
    raw = _env("MODEL_GATEWAY_METADATA_TIMEOUT")
    if not raw:
        return _DEFAULT_FETCH_TIMEOUT
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_FETCH_TIMEOUT


async def fetch_models() -> list[GatewayModel]:
    """Fetch and parse the extended ``GET /v1/models`` catalog from the gateway."""
    import httpx

    base_url = gateway_base_url()
    headers = {"Authorization": f"Bearer {gateway_api_key()}"}
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        resp = await client.get(f"{base_url}/models", headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("gateway /models response missing a 'data' list")

    models = [m for item in data if isinstance(item, dict) and (m := _parse_model(item))]
    if not models:
        raise ValueError("gateway /models returned an empty catalog")
    return models


async def get_models(force: bool = False) -> list[GatewayModel]:
    """Return gateway models, refreshing the cache when stale.

    Never raises: on fetch failure returns the last successful snapshot if any,
    otherwise the environment fallback. Safe to ``await`` from any async context.
    """
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache_at) < _ttl():
        return _cache
    async with _lock:
        now = time.monotonic()
        if not force and _cache is not None and (now - _cache_at) < _ttl():
            return _cache
        try:
            models = await fetch_models()
        except Exception:
            logger.warning(
                "gateway metadata fetch failed; using %s",
                "last-known cache" if _cache is not None else "env fallback",
                exc_info=True,
            )
            return _cache if _cache is not None else _env_fallback()
        _cache = models
        _cache_at = now
        return models


def snapshot() -> list[GatewayModel]:
    """Non-blocking accessor: last successful gateway catalog, else env fallback."""
    return _cache if _cache is not None else _env_fallback()


def reset_cache() -> None:
    """Test helper: drop the in-memory cache."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0
