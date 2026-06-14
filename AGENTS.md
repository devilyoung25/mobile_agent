# AGENTS.md

This repository is ON Mobile Agent: a corporate AgentEngine for enterprise
mobile SDLC flows. Treat the project as Microsoft Entra, Azure DevOps, Android,
policy, audit, and human-approval first.

## Current Shape

The repo is in migration. Do not assume legacy GitHub, Linear, or Slack behavior
is the target architecture.

```text
apps/dashboard/              Dashboard UI.
engine/agent-engine-core/    Provider-neutral engine package.
packages/model-launcher/     Model abstraction.
packages/mcp-toolset/        Generic MCP tool loading and policy.
packages/identity-entra/     Microsoft Entra identity provider.
packages/integration-azure-devops/
                             Azure DevOps MCP integration preset.
platform/dashboard_api/      Dashboard/session/orchestration API.
platform/integrations/       Runtime integrations outside the engine.
agent/                       Compatibility/runtime entrypoints during migration.
```

`agent/server.py` is still the LangGraph composition entrypoint. `agent/dashboard`
and `agent/integrations` are compatibility shims. Do not add new product code
there unless preserving existing imports is the smallest safe move.

### Engine (upstream vs. ours)

The real agent loop is `deepagents==0.6.8` (pinned, never modified).
`build_engine` (`engine/agent-engine-core/on_core/engine.py`) is a faithful
extraction of upstream's `create_deep_agent` call: same model/tools/subagent
wiring, same `DEFAULT_RECURSION_LIMIT`, same middleware order.

Middleware kept (brand-neutral): `SanitizeToolInputsMiddleware`,
`ModelCallLimitMiddleware`, `ToolErrorMiddleware`, `ToolArtifactMiddleware`,
`check_message_queue_before_model`, `ensure_no_empty_msg`,
`SandboxCircuitBreakerMiddleware`, `ModelFallbackMiddleware` (optional),
`SanitizeThinkingBlocksMiddleware`.

Removed on purpose (host/brand coupling): `refresh_github_proxy_before_model`
(GitHub), `SlackAssistantStatusMiddleware` and `notify_step_limit_reached`
(Slack). `check_message_queue_before_model` was *not* brand-specific — it drains
follow-up messages queued mid-run (Store `("queue", thread_id)/pending_messages`,
produced by `queue_message_for_thread`) and injects them before the next model
call; it was dropped by accident in the purge and restored, sitting between
`ToolArtifactMiddleware` and `ensure_no_empty_msg` exactly as upstream.

## Commands

Dependencies are managed with `uv`. Dashboard dependencies are managed from
`apps/dashboard`.

```bash
make install
make dev
make dev-all
make test
make lint
make format-check
```

Focused checks:

```bash
uv run pytest -vvv tests/test_azure_devops_mcp.py
uv run pytest -vvv tests/test_entra_routes.py
cd apps/dashboard && npm run typecheck
cd apps/dashboard && npm run lint
```

## Architecture Rules

- The engine must stay provider-neutral. No concrete Entra, Azure DevOps,
  GitHub, Slack, Linear, Android, Ollama, OpenAI, Anthropic, or Gemini policy
  should be hardcoded into engine internals.
- Identity belongs outside the engine. Tokens must never be exposed to the LLM,
  frontend, workspace, sandbox, logs, or generated prompts.
- Azure DevOps access goes through MCP/tool adapters plus policy. Do not build
  broad ad hoc Azure DevOps REST clients when the MCP integration covers the
  domain.
- Azure DevOps read-only context is allowed when policy permits it. Persistent
  actions such as PR creation, Work Item comments, pipeline runs, or PR updates
  require policy and human approval.
- GitHub support is legacy compatibility only. Do not make GitHub a central
  dependency for new workflows.
- Android Mobile Skills MCP is knowledge/context only. It must not run Gradle,
  ADB, emulators, installs, screenshots, or logcat.
- Mobile QA Runner owns real Gradle/ADB/emulator execution and must expose
  controlled, auditable actions.
- Workspace Manager owns clone, branch, credential, diff, and PR-preparation
  boundaries. The agent must not handle raw Git/Azure credentials.

## Development Rules

- Prefer small, reversible cuts. Do not do broad refactors unless the immediate
  migration step requires it.
- Keep compatibility shims until runtime imports and tests prove they can be
  deleted.
- When moving modules, first preserve behavior, then rename imports in a separate
  cleanup.
- Do not expose secret values from `.env`, token stores, screenshots, logs, or
  debug output.
- Add or adjust tests when changing policy, auth, token storage, MCP tool
  loading, or LangGraph composition.
- If a change alters security posture, state the new trust boundary and the
  failure mode explicitly.

## Product Direction

The intended flow is:

```text
Dashboard UI
-> Microsoft Entra Auth
-> Backend / SDLC Orchestrator
-> AgentEngine
-> Azure DevOps MCP
-> Android Mobile Engineering Skill
-> Android Mobile Skills MCP
-> Workspace Manager
-> Mobile QA Runner
-> Human Approval
-> Azure DevOps PR / Work Item update
```

Security, policy, audit, and human approval are product requirements, not later
hardening tasks.
