"""Azure DevOps MCP composition: Entra-minted bearer + the ADO toolset preset."""

import logging
from typing import Any

from integration_azure_devops import (
    AZURE_DEVOPS_PROMPT_FRAGMENT,
    DEFAULT_AZURE_DEVOPS_DOMAINS,
    READ_ONLY_POLICY,
    azure_devops_provider,
    is_azure_devops_read_only_tool,
    load_azure_devops_read_only_tools,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AZURE_DEVOPS_PROMPT_FRAGMENT",
    "DEFAULT_AZURE_DEVOPS_DOMAINS",
    "READ_ONLY_POLICY",
    "azure_devops_provider",
    "is_azure_devops_read_only_tool",
    "load_azure_devops_read_only_tools",
    "load_azure_devops_tools_for_actor",
]


async def load_azure_devops_tools_for_actor(actor_id: str | None) -> list[Any]:
    """Load the read-only ADO toolset authenticated as the triggering actor.

    Mints an Azure DevOps-scoped access token from the actor's stored Entra
    refresh token and passes it as the bearer for the remote MCP endpoint.
    Degrades to an unauthenticated load (stdio transport, or no tools) when
    no token can be minted.
    """
    bearer_token: str | None = None
    if actor_id:
        try:
            from identity_entra.tokens import get_azure_devops_access_token

            bearer_token = await get_azure_devops_access_token(actor_id)
        except Exception:
            logger.warning("Could not mint Azure DevOps token for %s", actor_id, exc_info=True)
    if not bearer_token and actor_id:
        logger.info(
            "No Azure DevOps bearer token for %s; remote MCP will be unauthenticated",
            actor_id,
        )
    return await load_azure_devops_read_only_tools(bearer_token=bearer_token)
