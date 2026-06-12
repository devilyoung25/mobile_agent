"""Azure DevOps MCP — re-exported from the integration-azure-devops package."""

from integration_azure_devops import (
    AZURE_DEVOPS_PROMPT_FRAGMENT,
    DEFAULT_AZURE_DEVOPS_DOMAINS,
    READ_ONLY_POLICY,
    azure_devops_provider,
    is_azure_devops_read_only_tool,
    load_azure_devops_read_only_tools,
)

__all__ = [
    "AZURE_DEVOPS_PROMPT_FRAGMENT",
    "DEFAULT_AZURE_DEVOPS_DOMAINS",
    "READ_ONLY_POLICY",
    "azure_devops_provider",
    "is_azure_devops_read_only_tool",
    "load_azure_devops_read_only_tools",
]
