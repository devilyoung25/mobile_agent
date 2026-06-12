# Module Boundaries

This repository is organized as an AgentEngine monorepo. Keep the engine small
and provider-neutral; attach enterprise systems through adapters.

## Layout

```text
engine/
  agent-engine-core/          # Engine package: prompt, assembly, middleware, sandbox state.

packages/
  model-launcher/             # Model registry and model construction.
  mcp-toolset/                # Generic MCP loading plus allow/deny policy.
  identity-entra/             # Microsoft Entra auth, token encryption, token cache.
  integration-azure-devops/   # Azure DevOps MCP preset and read-only policy.

platform/
  dashboard_api/              # FastAPI dashboard/session/orchestration routes.
  integrations/               # Runtime integrations used by the platform layer.

apps/
  dashboard/                  # Web dashboard.

agent/
  dashboard/                  # Compatibility shim for agent.dashboard.* imports.
  integrations/               # Compatibility shim for agent.integrations.* imports.
  server.py                   # Current LangGraph composition entrypoint.
```

## Rules

- `engine/agent-engine-core` must not know about Microsoft Entra, Azure DevOps,
  GitHub, Slack, Linear, or any concrete model provider.
- MCP integrations live outside the engine and expose tools through
  `mcp-toolset` policies.
- Identity providers live outside the engine. Tokens must not be exposed to the
  LLM, frontend, workspace, or shell tools.
- Dashboard/API code belongs in `platform/dashboard_api`, not in the engine.
- UI code belongs in `apps/dashboard`.
- The `agent.dashboard` and `agent.integrations` packages are compatibility
  shims only. New code should target the platform packages directly once the
  imports are fully migrated.

## Next Moves

The current compatibility shims intentionally keep runtime imports stable. A
future cleanup can migrate imports away from `agent.dashboard.*` and
`agent.integrations.*`, then delete those shims.
