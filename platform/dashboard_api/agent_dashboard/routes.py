"""Dashboard API routes (Entra auth, profile, settings, schedules, threads)."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from .admin import is_admin
from .agent_instructions import (
    AgentInstructionsCreate,
    AgentInstructionsUpdate,
    create_agent_instructions,
    delete_agent_instructions,
    get_agent_instructions,
    list_agent_instructions,
    normalize_repo_full_name,
    set_agent_instructions,
)
from .auth_tokens import upsert_auth_tokens
from .azure_devops_api import (
    get_project_usage,
    list_projects,
    list_pull_requests,
    list_repositories,
)
from .entra_oauth import (
    build_authorize_url as build_entra_authorize_url,
)
from .entra_oauth import (
    enforce_entra_allowlist,
    exchange_entra_code,
    identity_from_claims,
    new_code_verifier,
    validate_entra_id_token,
)
from .oauth import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    STATE_TTL_SECONDS,
    decode_state,
    hash_state_nonce,
    issue_session_for_identity,
    issue_state,
    new_state_nonce,
    require_same_origin_for_mutations,
    require_session,
    sanitize_redirect_to,
)
from .options import get_gateway_models, supported_models
from .profiles import (
    ProfileUpdate,
    get_profile,
    upsert_profile,
)
from .schedules import (
    ScheduleCreateBody,
    ScheduleUpdateBody,
    create_agent_schedule,
    delete_agent_schedule,
    list_agent_schedules,
    update_agent_schedule,
)
from .team_credentials import (
    DatadogCredentialsUpdate,
    LangSmithCredentialsUpdate,
    connect_datadog,
    connect_langsmith,
    disconnect_datadog,
    disconnect_langsmith,
    get_team_credentials_status,
)
from .team_settings import (
    TeamSettingsUpdate,
    get_team_default_model,
    get_team_default_subagent_model,
    get_team_settings,
    upsert_team_settings,
)
from .thread_api import (
    ThreadMessageBody,
    cancel_dashboard_thread,
    clear_dashboard_queued_messages,
    continue_dashboard_queued_messages,
    delete_dashboard_queued_message,
    delete_dashboard_thread,
    direct_dashboard_queued_message,
    get_dashboard_queued_messages,
    get_dashboard_thread,
    get_dashboard_thread_state,
    list_dashboard_threads,
    proxy_dashboard_thread_commands,
    proxy_dashboard_thread_history,
    proxy_dashboard_thread_run_cancel,
    proxy_dashboard_thread_stream_events,
    resume_dashboard_interrupt,
    send_dashboard_message,
    snapshot_dashboard_workspace,
    stream_dashboard_thread,
)
from .workspaces import (
    WorkspaceCreate,
    list_workspaces,
    pick_and_register_workspace,
    register_workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard/api",
    tags=["dashboard"],
    dependencies=[Depends(require_same_origin_for_mutations)],
)
ENTRA_STATE_COOKIE_NAME = "osw_entra_state"
ENTRA_PKCE_COOKIE_NAME = "osw_entra_pkce"


def _require_admin(session: dict[str, Any]) -> dict[str, Any]:
    if not is_admin(session.get("email")):
        raise HTTPException(403, "admin only")
    return session


_SESSION_DEP = Depends(require_session)


def _admin_session(session: dict[str, Any] = _SESSION_DEP) -> dict[str, Any]:
    return _require_admin(session)


_ADMIN_DEP = Depends(_admin_session)


def _api_base_url() -> str:
    v = os.environ.get("DASHBOARD_API_BASE_URL", "").rstrip("/")
    if not v:
        raise HTTPException(500, "DASHBOARD_API_BASE_URL not configured")
    return v


def _frontend_base_url() -> str:
    v = os.environ.get("DASHBOARD_BASE_URL", "").rstrip("/")
    if not v:
        raise HTTPException(500, "DASHBOARD_BASE_URL not configured")
    return v


def _cookie_security() -> tuple[bool, str]:
    """Cookie ``secure``/``samesite`` flags derived from the API scheme.

    Production serves the API over HTTPS and the dashboard is a separate
    (cross-site) origin, so the session cookie must be ``Secure; SameSite=None``.
    Local dev runs over ``http://localhost`` where ``Secure`` cookies are
    rejected and the frontend/API are same-site, so fall back to
    ``SameSite=Lax`` without ``Secure``.
    """
    if os.environ.get("DASHBOARD_API_BASE_URL", "").startswith("https://"):
        return True, "none"
    return False, "lax"


def _set_session_cookie(response: Response, jwt_token: str) -> None:
    secure, samesite = _cookie_security()
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _set_entra_state_cookie(response: Response, nonce: str) -> None:
    secure, _ = _cookie_security()
    response.set_cookie(
        key=ENTRA_STATE_COOKIE_NAME,
        value=nonce,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/dashboard/api/entra",
    )


def _set_entra_pkce_cookie(response: Response, code_verifier: str) -> None:
    secure, _ = _cookie_security()
    response.set_cookie(
        key=ENTRA_PKCE_COOKIE_NAME,
        value=code_verifier,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/dashboard/api/entra",
    )


def _clear_entra_cookies(response: Response) -> None:
    secure, _ = _cookie_security()
    response.delete_cookie(
        ENTRA_STATE_COOKIE_NAME, path="/dashboard/api/entra", samesite="lax", secure=secure
    )
    response.delete_cookie(
        ENTRA_PKCE_COOKIE_NAME, path="/dashboard/api/entra", samesite="lax", secure=secure
    )


@router.get("/entra/login")
async def entra_login(
    request: Request,
    redirect_to: str | None = None,
) -> RedirectResponse:
    safe_redirect = sanitize_redirect_to(redirect_to) or _frontend_base_url()
    nonce = new_state_nonce()
    state = issue_state(
        redirect_to=safe_redirect,
        nonce_hash=hash_state_nonce(nonce),
    )
    code_verifier = new_code_verifier()
    redirect_uri = f"{_api_base_url()}/dashboard/api/entra/callback"
    url = build_entra_authorize_url(
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )
    response = RedirectResponse(url, status_code=302)
    _set_entra_state_cookie(response, nonce)
    _set_entra_pkce_cookie(response, code_verifier)
    return response


@router.get("/entra/callback")
async def entra_callback(request: Request, code: str, state: str) -> RedirectResponse:
    state_payload = decode_state(state)
    nonce_hash = state_payload.get("nonce_hash")
    cookie_nonce = request.cookies.get(ENTRA_STATE_COOKIE_NAME)
    code_verifier = request.cookies.get(ENTRA_PKCE_COOKIE_NAME)
    if (
        not isinstance(nonce_hash, str)
        or not cookie_nonce
        or not hmac.compare_digest(hash_state_nonce(cookie_nonce), nonce_hash)
    ):
        raise HTTPException(400, "entra oauth state mismatch — please retry login")
    if not code_verifier:
        raise HTTPException(400, "entra pkce verifier missing — please retry login")

    redirect_to = sanitize_redirect_to(state_payload.get("redirect_to")) or _frontend_base_url()
    redirect_uri = f"{_api_base_url()}/dashboard/api/entra/callback"
    token_data = await exchange_entra_code(
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    claims = await validate_entra_id_token(token_data["id_token"], nonce=cookie_nonce)
    enforce_entra_allowlist(claims)
    identity = identity_from_claims(claims)
    await upsert_auth_tokens(
        actor_id=identity.actor_id,
        provider=identity.provider,
        tenant_id=identity.tenant_id,
        email=identity.normalized_email,
        token_data=token_data,
    )

    session_jwt = issue_session_for_identity(
        actor_id=identity.actor_id,
        auth_provider=identity.provider,
        email=identity.normalized_email,
        name=identity.display_name,
        tenant_id=identity.tenant_id,
    )
    response = RedirectResponse(redirect_to, status_code=302)
    _set_session_cookie(response, session_jwt)
    _clear_entra_cookies(response)
    return response


@router.post("/auth/logout")
async def auth_logout() -> Response:
    response = Response(status_code=204)
    secure, samesite = _cookie_security()
    response.delete_cookie(COOKIE_NAME, path="/", samesite=samesite, secure=secure)
    return response


@router.get("/me")
async def me(session: dict[str, Any] = _SESSION_DEP) -> dict[str, Any]:
    return {
        "login": session["sub"],
        "actor_id": session.get("actor_id") or session["sub"],
        "auth_provider": session.get("auth_provider") or "entra",
        "email": session.get("email"),
        "name": session.get("name"),
        "tenant_id": session.get("tenant_id"),
        "avatar_url": session.get("avatar_url"),
        "is_admin": is_admin(session.get("email")),
    }


@router.get("/options")
async def options() -> dict[str, Any]:
    # Warm the gateway capability cache so the catalog reflects the gateway.
    await get_gateway_models()
    agent_model, agent_effort = await get_team_default_model("agent")
    subagent_model, subagent_effort = await get_team_default_subagent_model("agent")
    return {
        "models": supported_models(),
        "default_agent_model": agent_model,
        "default_agent_reasoning_effort": agent_effort,
        "default_agent_subagent_model": subagent_model,
        "default_agent_subagent_reasoning_effort": subagent_effort,
    }


@router.get("/profile")
async def get_my_profile(
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    profile = await get_profile(session["sub"])
    return profile or {}


@router.put("/profile")
async def put_my_profile(
    update: ProfileUpdate,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    update.validate_pairing()
    return await upsert_profile(session["sub"], session.get("email") or "", update)


@router.get("/team-settings")
async def api_get_team_settings(
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await get_team_settings()


@router.put("/team-settings")
async def api_put_team_settings(
    update: TeamSettingsUpdate,
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await upsert_team_settings(update)


@router.get("/team-credentials")
async def api_get_team_credentials(
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await get_team_credentials_status()


@router.put("/team-credentials/datadog")
async def api_connect_datadog(
    update: DatadogCredentialsUpdate,
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await connect_datadog(update)


@router.delete("/team-credentials/datadog")
async def api_disconnect_datadog(
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await disconnect_datadog()


@router.put("/team-credentials/langsmith")
async def api_connect_langsmith(
    update: LangSmithCredentialsUpdate,
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await connect_langsmith(update)


@router.delete("/team-credentials/langsmith")
async def api_disconnect_langsmith(
    _admin: dict[str, Any] = _ADMIN_DEP,
) -> dict[str, Any]:
    return await disconnect_langsmith()


@router.get("/agent-instructions")
async def api_list_agent_instructions(
    session: dict[str, Any] = _SESSION_DEP,
) -> list[dict[str, Any]]:
    del session
    return await list_agent_instructions()


@router.post("/agent-instructions")
async def api_create_agent_instructions(
    body: AgentInstructionsCreate,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await create_agent_instructions(body.full_name, session["sub"])


@router.get("/agent-instructions/{full_name:path}")
async def api_get_agent_instructions(
    full_name: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    full_name = normalize_repo_full_name(full_name)
    record = await get_agent_instructions(full_name)
    if not record:
        raise HTTPException(404, "agent instructions not found")
    return record


@router.put("/agent-instructions/{full_name:path}")
async def api_update_agent_instructions(
    full_name: str,
    body: AgentInstructionsUpdate,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    full_name = normalize_repo_full_name(full_name)
    return await set_agent_instructions(full_name, body.instructions)


@router.delete("/agent-instructions/{full_name:path}")
async def api_delete_agent_instructions(
    full_name: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> Response:
    full_name = normalize_repo_full_name(full_name)
    record = await get_agent_instructions(full_name)
    if not record:
        raise HTTPException(404, "agent instructions not found")
    await delete_agent_instructions(full_name)
    return Response(status_code=204)


@router.get("/schedules")
async def api_list_schedules(
    session: dict[str, Any] = _SESSION_DEP,
) -> list[dict[str, Any]]:
    return await list_agent_schedules(session["sub"], email=session.get("email"))


@router.post("/schedules")
async def api_create_schedule(
    body: ScheduleCreateBody,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await create_agent_schedule(session["sub"], body, email=session.get("email"))


@router.patch("/schedules/{schedule_id}")
async def api_update_schedule(
    schedule_id: str,
    body: ScheduleUpdateBody,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await update_agent_schedule(
        schedule_id, session["sub"], body, email=session.get("email")
    )


@router.delete("/schedules/{schedule_id}")
async def api_delete_schedule(
    schedule_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> Response:
    await delete_agent_schedule(schedule_id, session["sub"], email=session.get("email"))
    return Response(status_code=204)


@router.get("/azure/projects")
async def api_azure_projects(
    session: dict[str, Any] = _SESSION_DEP,
) -> list[dict[str, Any]]:
    return await list_projects(session["sub"])


@router.get("/azure/repos")
async def api_azure_repos(
    project: str | None = None,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    repositories = await list_repositories(session["sub"], project)
    return {"repositories": repositories}


@router.get("/azure/pull-requests")
async def api_azure_pull_requests(
    project: str,
    status: str = "active",
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    pull_requests = await list_pull_requests(session["sub"], project, status=status)
    return {"pull_requests": pull_requests}


@router.get("/azure/usage")
async def api_azure_usage(
    project: str,
    period: str = "30d",
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    normalized_period = period if period in {"7d", "30d", "all"} else "30d"
    return await get_project_usage(session["sub"], project, period=normalized_period)


@router.get("/workspaces")
async def api_list_workspaces(
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return {"workspaces": await list_workspaces(session["sub"])}


@router.post("/workspaces")
async def api_register_workspace(
    body: WorkspaceCreate,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await register_workspace(session["sub"], body)


@router.post("/workspaces/pick")
async def api_pick_workspace(
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await pick_and_register_workspace(session["sub"])


@router.get("/threads")
async def api_list_threads(
    all: bool = False,
    session: dict[str, Any] = _SESSION_DEP,
) -> list[dict[str, Any]]:
    return await list_dashboard_threads(session["sub"], email=session.get("email"), include_all=all)


@router.get("/threads/{thread_id}")
async def api_get_thread(
    thread_id: str,
    mark_viewed: bool = True,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await get_dashboard_thread(
        thread_id,
        session["sub"],
        email=session.get("email"),
        mark_viewed=mark_viewed,
    )


@router.post("/threads/{thread_id}/messages")
async def api_send_thread_message(
    thread_id: str,
    body: ThreadMessageBody,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await send_dashboard_message(thread_id, session["sub"], body, email=session.get("email"))


@router.get("/threads/{thread_id}/queued")
async def api_get_thread_queued_messages(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await get_dashboard_queued_messages(thread_id, session["sub"], email=session.get("email"))


@router.delete("/threads/{thread_id}/queued")
async def api_clear_thread_queued_messages(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await clear_dashboard_queued_messages(thread_id, session["sub"], email=session.get("email"))


@router.delete("/threads/{thread_id}/queued/{message_id}")
async def api_delete_thread_queued_message(
    thread_id: str,
    message_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await delete_dashboard_queued_message(
        thread_id,
        message_id,
        session["sub"],
        email=session.get("email"),
    )


@router.post("/threads/{thread_id}/queued/{message_id}/direct")
async def api_direct_thread_queued_message(
    thread_id: str,
    message_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await direct_dashboard_queued_message(
        thread_id,
        message_id,
        session["sub"],
        email=session.get("email"),
        auth_provider=session.get("auth_provider") or "entra",
        actor_id=session.get("actor_id") or session["sub"],
    )


@router.post("/threads/{thread_id}/queued/continue")
async def api_continue_thread_queued_messages(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await continue_dashboard_queued_messages(
        thread_id,
        session["sub"],
        email=session.get("email"),
        auth_provider=session.get("auth_provider") or "entra",
        actor_id=session.get("actor_id") or session["sub"],
    )


@router.post("/threads/{thread_id}/resume")
async def api_resume_thread_interrupt(
    thread_id: str,
    body: dict[str, Any],
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    decisions = body.get("decisions") if isinstance(body, dict) else None
    if not isinstance(decisions, list) or not decisions:
        raise HTTPException(status_code=400, detail="decisions_required")
    return await resume_dashboard_interrupt(
        thread_id,
        decisions,
        session["sub"],
        email=session.get("email"),
    )


@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def api_cancel_thread_run(
    thread_id: str,
    run_id: str,
    session: dict[str, Any] = _SESSION_DEP,
    wait: str = "0",
    action: str = "interrupt",
) -> Response:
    status_code, content, media_type = await proxy_dashboard_thread_run_cancel(
        thread_id,
        run_id,
        session["sub"],
        wait=wait,
        action=action,
        email=session.get("email"),
    )
    return Response(content=content, status_code=status_code, media_type=media_type)


@router.post("/threads/{thread_id}/cancel")
async def api_cancel_thread(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await cancel_dashboard_thread(thread_id, session["sub"], email=session.get("email"))


@router.delete("/threads/{thread_id}")
async def api_delete_thread(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> Response:
    await delete_dashboard_thread(thread_id, session["sub"], email=session.get("email"))
    return Response(status_code=204)


@router.get("/threads/{thread_id}/state")
async def api_get_thread_state(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await get_dashboard_thread_state(thread_id, session["sub"], email=session.get("email"))


@router.post("/threads/{thread_id}/workspace/snapshot")
async def api_workspace_snapshot(
    thread_id: str,
    session: dict[str, Any] = _SESSION_DEP,
) -> dict[str, Any]:
    return await snapshot_dashboard_workspace(
        thread_id, session["sub"], email=session.get("email")
    )


@router.post("/threads/{thread_id}/stream/events")
async def api_thread_stream_events(
    thread_id: str,
    request: Request,
    session: dict[str, Any] = _SESSION_DEP,
) -> StreamingResponse:
    body = await request.body()
    stream = await proxy_dashboard_thread_stream_events(
        thread_id,
        session["sub"],
        body,
        email=session.get("email"),
        content_type=request.headers.get("content-type", "application/json"),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/threads/{thread_id}/commands")
async def api_thread_commands(
    thread_id: str,
    request: Request,
    session: dict[str, Any] = _SESSION_DEP,
) -> Response:
    body = await request.body()
    status_code, content, media_type = await proxy_dashboard_thread_commands(
        thread_id,
        session["sub"],
        body,
        email=session.get("email"),
        content_type=request.headers.get("content-type", "application/json"),
        auth_provider=session.get("auth_provider") or "entra",
        actor_id=session.get("actor_id") or session["sub"],
    )
    return Response(content=content, status_code=status_code, media_type=media_type)


@router.post("/threads/{thread_id}/history")
async def api_thread_history(
    thread_id: str,
    request: Request,
    session: dict[str, Any] = _SESSION_DEP,
) -> Response:
    body = await request.body()
    status_code, content, media_type = await proxy_dashboard_thread_history(
        thread_id,
        session["sub"],
        body,
        email=session.get("email"),
        content_type=request.headers.get("content-type", "application/json"),
    )
    return Response(content=content, status_code=status_code, media_type=media_type)


@router.get("/threads/{thread_id}/stream")
async def api_stream_thread(
    thread_id: str,
    request: Request,
    session: dict[str, Any] = _SESSION_DEP,
) -> StreamingResponse:
    last_event_id = request.headers.get("last-event-id")

    async def event_generator():
        async for chunk in stream_dashboard_thread(
            thread_id, session["sub"], email=session.get("email"), last_event_id=last_event_id
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
