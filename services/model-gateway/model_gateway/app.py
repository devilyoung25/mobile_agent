"""ON Model Gateway — OpenAI-compatible, multi-provider facade.

- ``GET  /health``               liveness.
- ``GET  /v1/models``            aggregated catalog across providers, each tagged
                                 with ``provider`` and ``available`` (reactive to
                                 rate limits) — the source of truth the UI renders.
- ``GET  /v1/providers``         providers + their models grouped (for the UI tabs).
- ``POST /v1/chat/completions``  routes to the model's provider; records a 429 as
                                 a temporary unavailability so the UI greys it out.

Provider keys live only here (gateway's own ``.env``); the engine never sees them.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import catalog, config

logger = logging.getLogger("model_gateway")

app = FastAPI(title="ON Model Gateway", version="0.2.0")


def _authorized(request: Request) -> bool:
    required = config.inbound_api_key()
    if not required:
        return True
    return request.headers.get("authorization", "") == f"Bearer {required}"


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "on-model-gateway"}


@app.get("/v1/models")
async def list_models() -> dict:
    models = await catalog.build_catalog()
    return {"object": "list", "data": [m.to_public() for m in models]}


@app.get("/v1/providers")
async def list_providers() -> dict:
    """Models grouped by provider, for the dashboard's provider-tab selector."""
    models = await catalog.build_catalog()
    grouped: dict[str, dict] = {}
    for provider in config.providers():
        grouped[provider.id] = {"id": provider.id, "label": provider.label, "models": []}
    for m in models:
        grouped.setdefault(m.provider, {"id": m.provider, "label": m.provider, "models": []})
        grouped[m.provider]["models"].append(m.to_public())
    return {"providers": list(grouped.values())}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not _authorized(request):
        return JSONResponse({"error": {"message": "Unauthorized", "code": 401}}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "Invalid JSON body"}}, status_code=400)

    requested = body.get("model") if isinstance(body.get("model"), str) else ""
    entry = await catalog.lookup(requested)
    if entry is not None:
        provider = config.provider_by_id(entry.provider)
        upstream_model = entry.upstream_model
    else:
        fallback = config.default_fallback()
        if not fallback:
            return JSONResponse(
                {"error": {"message": f"Unknown model '{requested}' and no default configured"}},
                status_code=404,
            )
        provider = config.provider_by_id(fallback[0])
        upstream_model = fallback[1]

    if provider is None:
        return JSONResponse(
            {"error": {"message": "No provider configured for the requested model"}},
            status_code=503,
        )

    payload = {k: v for k, v in body.items() if k not in config.drop_params()}
    payload["model"] = upstream_model
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {provider.api_key}"}
    url = f"{provider.base_url}/chat/completions"
    track_id = requested or upstream_model

    if bool(body.get("stream")):

        async def proxy_stream():
            async with httpx.AsyncClient(timeout=config.timeout()) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        catalog.mark_unavailable(track_id, _retry_after(resp))
                    else:
                        catalog.mark_available(track_id)
                    if resp.status_code != 200:
                        yield await resp.aread()
                        return
                    async for chunk in resp.aiter_raw():
                        yield chunk

        return StreamingResponse(proxy_stream(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=config.timeout()) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("upstream request failed: %s", type(exc).__name__)
        return JSONResponse({"error": {"message": "upstream request failed"}}, status_code=502)

    if resp.status_code == 429:
        catalog.mark_unavailable(track_id, _retry_after(resp))
    elif resp.status_code < 400:
        catalog.mark_available(track_id)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
