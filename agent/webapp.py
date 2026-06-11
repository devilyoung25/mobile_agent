"""FastAPI app shell: mounts the dashboard API alongside the LangGraph server."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .dashboard import router as dashboard_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    from .utils.sandbox import validate_sandbox_startup_config

    validate_sandbox_startup_config()
    yield


app = FastAPI(lifespan=lifespan)

DASHBOARD_ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
if DASHBOARD_ALLOWED_ORIGINS:
    if "*" in DASHBOARD_ALLOWED_ORIGINS:
        raise RuntimeError(
            "DASHBOARD_ALLOWED_ORIGINS must not include '*' when allow_credentials=True"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DASHBOARD_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

app.include_router(dashboard_router)

LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL") or os.environ.get(
    "LANGGRAPH_URL_PROD", "http://localhost:2024"
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
