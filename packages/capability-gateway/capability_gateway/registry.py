"""Built-in capability and domain-pack registry."""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import (
    CapabilityCredential,
    CapabilityDescriptor,
    CapabilityImplementation,
    CapabilityPolicy,
)

MOBILE_PACK_ID = "mobile"
MOBILE_PACK_VERSION = "0.1.0"
AZURE_DEVOPS_READ_CAPABILITY = "azure_devops.read"


@dataclass(frozen=True)
class DomainPackManifest:
    """Minimal versioned manifest for a domain pack."""

    id: str
    version: str
    capabilities: tuple[str, ...]


def get_domain_pack(domain_pack: str) -> DomainPackManifest | None:
    normalized = domain_pack.strip().lower()
    if normalized == MOBILE_PACK_ID:
        return DomainPackManifest(
            id=MOBILE_PACK_ID,
            version=MOBILE_PACK_VERSION,
            capabilities=(AZURE_DEVOPS_READ_CAPABILITY,),
        )
    return None


def get_capability_descriptor(name: str) -> CapabilityDescriptor | None:
    if name == AZURE_DEVOPS_READ_CAPABILITY:
        return _azure_devops_read_descriptor()
    return None


def _azure_devops_read_descriptor() -> CapabilityDescriptor:
    # Lazy import avoids a package import cycle: integration_azure_devops imports
    # capability_gateway for the generic provider/policy types.
    from integration_azure_devops import READ_ONLY_POLICY

    return CapabilityDescriptor(
        name=AZURE_DEVOPS_READ_CAPABILITY,
        description=(
            "Read-only Azure DevOps context: projects, work items, repositories, "
            "branches, pull requests, builds, pipelines, test plans, search, and wiki."
        ),
        input_schema=None,
        output_schema=None,
        implementation=CapabilityImplementation(
            kind="mcp",
            config={"provider": "azure-devops"},
        ),
        policy=CapabilityPolicy(mode="allow", tool_policy=READ_ONLY_POLICY),
        credential=CapabilityCredential(kind="azure_devops_bearer"),
        provenance_tags=("azure-devops", "read-only", "mobile"),
    )
