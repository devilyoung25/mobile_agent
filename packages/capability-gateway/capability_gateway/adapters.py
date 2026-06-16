"""Capability adapters.

Adapters know how to reach a backing implementation. Governance stays in the
gateway pipeline; adapters only load raw tools from their origin.

Today the only implementation kind is ``mcp``. The :class:`CapabilityAdapter`
protocol and the ``kind`` dispatch in ``gateway`` keep MCP as *one* adapter
rather than the root abstraction, so a future kind (e.g. a REST integration or
a ``native`` in-process capability) is an additive change, not a rewrite.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import BaseTool

from .capabilities import CapabilityContext, CapabilityDescriptor, ResolvedCredential

logger = logging.getLogger(__name__)


class McpAdapter:
    """Adapter for capabilities backed by MCP servers."""

    async def load_tools(
        self,
        descriptor: CapabilityDescriptor,
        credential: ResolvedCredential,
        context: CapabilityContext,
    ) -> list[BaseTool]:
        provider_name = str(descriptor.implementation.config.get("provider", "")).strip()
        if provider_name == "azure-devops":
            provider = _azure_devops_provider(credential)
        else:
            logger.warning(
                "Unsupported MCP capability provider: capability=%s provider=%s",
                descriptor.name,
                provider_name or "<empty>",
            )
            return []

        if provider is None:
            logger.info(
                "Capability provider unavailable: capability=%s domain_pack=%s",
                descriptor.name,
                context.domain_pack,
            )
            return []

        timeout = getattr(provider, "timeout_seconds", 30.0)
        try:
            tools = await asyncio.wait_for(provider.load_tools(), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "Capability provider timed out: capability=%s timeout_seconds=%s",
                descriptor.name,
                timeout,
            )
            return []
        except Exception:
            logger.warning(
                "Capability provider failed: capability=%s",
                descriptor.name,
                exc_info=True,
            )
            return []
        return [tool for tool in tools if isinstance(tool, BaseTool)]


def _azure_devops_provider(credential: ResolvedCredential):
    from integration_azure_devops import azure_devops_provider

    bearer_token = credential.value if credential.kind == "azure_devops_bearer" else None
    return azure_devops_provider(bearer_token=bearer_token)
