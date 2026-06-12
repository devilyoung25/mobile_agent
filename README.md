# ON Mobile Agent

Enterprise AgentEngine for mobile SDLC workflows.

ON Mobile Agent is a Microsoft/Azure DevOps-first AgentEngine runtime.
The product goal is not a generic coding agent. It is an internal
AgentEngine for mobile engineering teams that need controlled work-item intake,
repository context, code changes, build/test feedback, mobile QA evidence, human
approval, and Azure DevOps reporting.

## Product Focus

- Microsoft Entra authentication for corporate users.
- Azure DevOps MCP as the source of Boards, Work Items, Repos, Pull Requests,
  Pipelines, Builds, Test Plans, Wiki, and Search context.
- Provider-neutral model launching, including Ollama and cloud models.
- Android Mobile Engineering Skill as the primary technical skill.
- Android Mobile Skills MCP for Android knowledge and workflow guidance.
- Mobile QA Runner for Gradle, ADB, emulator, screenshots, logcat, and QA reports.
- Workspace Manager for isolated repository checkout, branch state, diff capture,
  and PR preparation.
- Policy, audit, and human approval gates before persistent actions.

## Runtime Boundary

```text
apps/
  dashboard/                 Corporate dashboard UI.

engine/
  agent-engine-core/         Provider-neutral AgentEngine package.

packages/
  model-launcher/            Model registry and model construction.
  mcp-toolset/               Generic MCP loading plus tool policy.
  identity-entra/            Microsoft Entra identity provider.
  integration-azure-devops/  Azure DevOps MCP preset and read-only policy.

platform/
  dashboard_api/             Dashboard/session/orchestration API.
  integrations/              Runtime integrations outside the engine.

agent/
  server.py                  Current LangGraph composition entrypoint.
  dashboard/                 Temporary compatibility shim.
  integrations/              Temporary compatibility shim.
```

The current `agent/` package still exists for runtime compatibility. New product
code should move toward `engine/`, `packages/`, `platform/`, and `apps/`.

## Security Rules

- Tokens are never exposed to the frontend, LLM, workspace, or sandbox tools.
- Microsoft Entra tokens are stored only through encrypted backend token storage.
- Azure DevOps write actions require policy and human approval.
- The agent must not merge PRs, force-push, delete branches, change permissions,
  approve PRs, or close Work Items automatically.
- MCP servers provide structured tools and context. They do not replace the
  orchestrator or policy layer.
- Android Mobile Skills MCP provides knowledge only. Real Gradle, ADB, emulator,
  screenshot, and logcat execution belongs to Mobile QA Runner.

## Local Development

Install dependencies:

```bash
make install
```

Run backend and dashboard together:

```bash
make dev-all
```

Run tests:

```bash
make test
```

Run lint and format checks:

```bash
make lint
make format-check
```

## Documentation

- [Module boundaries](docs/architecture/module-boundaries.md)

## License

This codebase remains MIT licensed. Keep license obligations intact when
renaming, redistributing, or extracting internal packages.
