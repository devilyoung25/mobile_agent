# Capability Gateway

The Capability Gateway is the Tools & Domain boundary consumed by
agent-composition. It resolves domain-pack capabilities into governed LangChain
tools.

## Entrypoint

```python
async def load_tools_for(
    actor_id: str | None,
    *,
    domain_pack: str,
    project_scope: list[str],
) -> list[BaseTool]
```

The engine never calls this directly. Composition passes the actor and
`project_scope`; the gateway returns only resolved tools. Credentials, provider
details, headers, and server configs stay server-side.

## CapabilityDescriptor

```text
name
description
input_schema
output_schema
implementation { kind: "mcp" | "rest", config }
policy { mode: "allow" | "deny" | "requires_approval", tool_policy? }
credential { kind: "none" | "azure_devops_bearer" }
provenance_tags
```

Domain packs reference capabilities by `name`. The gateway resolves the
descriptor, mints any required credential for the actor, applies policy, dispatches
to the adapter, annotates returned tools with non-sensitive capability metadata,
and emits local audit/provenance logs.

## MVP

`domain_pack="mobile"` currently enables one capability:

- `azure_devops.read` — Azure DevOps MCP read-only tools.

Business Knowledge MCP and Android Knowledge MCP are intentionally not part of
this cut.
