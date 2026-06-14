"""Capability Gateway contracts.

The gateway exposes governed capabilities as LangChain tools. A capability can
be backed by an MCP server, a REST API, an SDK, or a future internal adapter; the
agent only receives already-resolved tools plus non-sensitive provenance
metadata.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from langchain_core.tools import BaseTool, StructuredTool

from .policy import ToolPolicy

CapabilityImplementationKind = Literal["mcp", "rest"]
CapabilityPolicyMode = Literal["allow", "deny", "requires_approval"]
CapabilityCredentialKind = Literal["none", "azure_devops_bearer"]


@dataclass(frozen=True)
class CapabilityImplementation:
    """Where and how a capability is implemented."""

    kind: CapabilityImplementationKind
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("mcp", "rest"):
            raise ValueError(f"Unsupported capability implementation kind: {self.kind!r}")


@dataclass(frozen=True)
class CapabilityPolicy:
    """Governance policy attached to a capability."""

    mode: CapabilityPolicyMode = "allow"
    tool_policy: ToolPolicy | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("allow", "deny", "requires_approval"):
            raise ValueError(f"Unsupported capability policy mode: {self.mode!r}")

    @property
    def requires_approval(self) -> bool:
        return self.mode == "requires_approval"


@dataclass(frozen=True)
class CapabilityCredential:
    """Credential required by a capability.

    This describes the credential type only. Secret material is resolved
    server-side by the gateway and never stored in the descriptor.
    """

    kind: CapabilityCredentialKind = "none"

    def __post_init__(self) -> None:
        if self.kind not in ("none", "azure_devops_bearer"):
            raise ValueError(f"Unsupported capability credential kind: {self.kind!r}")


@dataclass(frozen=True)
class ResolvedCredential:
    """Server-side credential material for adapter dispatch."""

    kind: CapabilityCredentialKind
    value: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Stable contract a domain-pack references by name."""

    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    implementation: CapabilityImplementation
    policy: CapabilityPolicy = field(default_factory=CapabilityPolicy)
    credential: CapabilityCredential = field(default_factory=CapabilityCredential)
    provenance_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("CapabilityDescriptor.name is required")
        if not self.description.strip():
            raise ValueError("CapabilityDescriptor.description is required")
        _validate_schema("input_schema", self.input_schema)
        _validate_schema("output_schema", self.output_schema)


@dataclass(frozen=True)
class CapabilityContext:
    """Per-run context available to gateway governance and adapters."""

    actor_id: str | None
    domain_pack: str
    project_scope: tuple[str, ...]
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Adapter contract for a concrete capability origin."""

    async def load_tools(
        self,
        descriptor: CapabilityDescriptor,
        credential: ResolvedCredential,
        context: CapabilityContext,
    ) -> list[BaseTool]: ...


def capability_metadata(
    descriptor: CapabilityDescriptor,
) -> dict[str, object]:
    """Non-sensitive metadata exposed to composition and the approval gate."""

    return {
        "name": descriptor.name,
        "requires_approval": descriptor.policy.requires_approval,
        "provenance_tags": list(descriptor.provenance_tags),
        "implementation_kind": descriptor.implementation.kind,
    }


def attach_capability_metadata(
    tool: BaseTool,
    descriptor: CapabilityDescriptor,
) -> BaseTool:
    """Attach capability metadata to a tool, wrapping only if direct mutation fails."""

    metadata = {"capability": capability_metadata(descriptor)}
    try:
        current = getattr(tool, "metadata", None)
        next_metadata = dict(current) if isinstance(current, dict) else {}
        next_metadata.update(metadata)
        tool.metadata = next_metadata
        if getattr(tool, "metadata", {}).get("capability") == metadata["capability"]:
            return tool
    except Exception:
        pass

    if hasattr(tool, "model_copy"):
        try:
            return tool.model_copy(update={"metadata": metadata})
        except Exception:
            pass

    return _wrap_tool_with_metadata(tool, metadata)


def _wrap_tool_with_metadata(tool: BaseTool, metadata: dict[str, object]) -> BaseTool:
    async def _arun(**kwargs: Any) -> Any:
        return await tool.ainvoke(kwargs)

    def _run(**kwargs: Any) -> Any:
        return tool.invoke(kwargs)

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=tool.name,
        description=tool.description or "",
        args_schema=getattr(tool, "args_schema", None),
        metadata=metadata,
    )


def _validate_schema(field_name: str, schema: dict[str, Any] | None) -> None:
    if schema is not None and not isinstance(schema, dict):
        raise ValueError(f"CapabilityDescriptor.{field_name} must be a dict or None")
