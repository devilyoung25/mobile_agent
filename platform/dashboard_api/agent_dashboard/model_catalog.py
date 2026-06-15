"""Proxy the internal ON Model Gateway catalog to the dashboard.

The gateway is internal (not exposed to the browser); the dashboard fetches its
provider/model catalog through the backend. Fail-soft: on any gateway problem we
return an empty catalog so the UI falls back to its plain model selector.
"""

from __future__ import annotations

import os

import httpx


async def get_model_catalog() -> dict:
    base = os.environ.get("MODEL_GATEWAY_BASE_URL", "").strip().rstrip("/")
    if not base:
        return {"providers": []}
    key = os.environ.get("MODEL_GATEWAY_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/providers", headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {"providers": []}
    if isinstance(data, dict) and isinstance(data.get("providers"), list):
        return data
    return {"providers": []}
