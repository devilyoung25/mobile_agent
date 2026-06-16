"""Capability Gateway entrypoint."""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from .adapters import McpAdapter
from .capabilities import (
    CapabilityAdapter,
    CapabilityContext,
    CapabilityCredential,
    CapabilityDescriptor,
    ResolvedCredential,
    attach_capability_metadata,
)
from .policy import filter_tools
from .registry import get_capability_descriptor, get_domain_pack

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, CapabilityAdapter] = {
    "mcp": McpAdapter(),
}


async def load_tools_for(
    actor_id: str | None,
    *,
    domain_pack: str,
    project_scope: list[str],
) -> list[BaseTool]:
    """Resolve governed tools for a run.

    This is the concrete implementation of the ToolLoader seam consumed by
    agent-composition. It returns only resolved LangChain tools; provider
    details and credential material stay inside this package.
    """

    context = CapabilityContext(
        actor_id=actor_id,
        domain_pack=domain_pack,
        project_scope=tuple(project_scope),
    )
    manifest = get_domain_pack(domain_pack)
    if manifest is None:
        _audit(
            "domain_pack_unknown",
            context=context,
            domain_pack=domain_pack,
        )
        return []

    resolved: list[BaseTool] = []
    for capability_name in manifest.capabilities:
        descriptor = get_capability_descriptor(capability_name)
        if descriptor is None:
            _audit(
                "capability_missing",
                context=context,
                capability=capability_name,
            )
            continue
        resolved.extend(await _load_capability_tools(descriptor, context))
    return resolved


async def _load_capability_tools(
    descriptor: CapabilityDescriptor,
    context: CapabilityContext,
) -> list[BaseTool]:
    if descriptor.policy.mode == "deny":
        _audit("capability_denied", context=context, capability=descriptor.name)
        return []

    credential = await _resolve_credential(descriptor.credential, context)
    if credential is None:
        _audit(
            "credential_unavailable",
            context=context,
            capability=descriptor.name,
            credential_kind=descriptor.credential.kind,
        )
        return []

    adapter = _ADAPTERS.get(descriptor.implementation.kind)
    if adapter is None:
        _audit(
            "adapter_missing",
            context=context,
            capability=descriptor.name,
            implementation_kind=descriptor.implementation.kind,
        )
        return []

    try:
        raw_tools = await adapter.load_tools(descriptor, credential, context)
    except Exception:
        logger.warning(
            "Capability dispatch failed: capability=%s implementation_kind=%s",
            descriptor.name,
            descriptor.implementation.kind,
            exc_info=True,
        )
        return []

    filtered = filter_tools(raw_tools, descriptor.policy.tool_policy)
    tools = [attach_capability_metadata(tool, descriptor) for tool in filtered.allowed]
    _audit(
        "capability_loaded",
        context=context,
        capability=descriptor.name,
        implementation_kind=descriptor.implementation.kind,
        tool_count=len(tools),
        blocked_count=len(filtered.blocked),
        requires_approval=descriptor.policy.requires_approval,
    )
    return tools


async def _resolve_credential(
    credential: CapabilityCredential,
    context: CapabilityContext,
) -> ResolvedCredential | None:
    if credential.kind == "none":
        return ResolvedCredential(kind="none")
    if credential.kind == "azure_devops_bearer":
        if not context.actor_id:
            return None
        token = await _mint_azure_devops_bearer(context.actor_id)
        if not token:
            return None
        return ResolvedCredential(kind="azure_devops_bearer", value=token)
    return None


async def _mint_azure_devops_bearer(actor_id: str) -> str | None:
    try:
        from identity_entra.tokens import get_azure_devops_access_token

        return await get_azure_devops_access_token(actor_id)
    except Exception:
        logger.warning(
            "Could not mint Azure DevOps token for capability gateway actor=%s",
            actor_id,
            exc_info=True,
        )
        return None


def _audit(
    event: str,
    *,
    context: CapabilityContext,
    capability: str | None = None,
    **fields: object,
) -> None:
    logger.info(
        "capability_gateway_event event=%s capability=%s domain_pack=%s actor_present=%s scope_count=%d correlation_id=%s %s",
        event,
        capability or "",
        context.domain_pack,
        bool(context.actor_id),
        len(context.project_scope),
        context.correlation_id,
        _format_audit_fields(fields),
    )


def _format_audit_fields(fields: dict[str, object]) -> str:
    safe = {
        key: value
        for key, value in fields.items()
        if "token" not in key.lower()
        and "secret" not in key.lower()
        and "authorization" not in key.lower()
    }
    return " ".join(f"{key}={value}" for key, value in sorted(safe.items()))
