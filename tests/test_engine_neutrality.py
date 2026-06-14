"""Mechanical guard: engine-core must stay provider- and domain-neutral.

The agentic engine (``engine/agent-engine-core/on_core``) receives already-resolved
models, tools, prompt, and backend. It must NOT import provider SDKs, integration
packages, identity providers, the MCP runtime, the model launcher, or the
composition app. This test fails the moment a leak is introduced, so neutrality is
enforced mechanically instead of by discipline.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE_ROOT = (
    Path(__file__).resolve().parents[1] / "engine" / "agent-engine-core" / "on_core"
)

FORBIDDEN_TOP_LEVEL = {
    # provider SDKs / provider-specific langchain bindings
    "openai",
    "anthropic",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_google_genai",
    # product layers the neutral engine must not know about
    "integration_azure_devops",
    "identity_entra",
    "mcp_toolset",
    "model_launcher",
    "agent",  # the composition app
}

# Pre-existing leaks tracked as debt to remove. Keep this shrinking only: any NEW
# leak, or an allowlisted file importing a DIFFERENT forbidden module, still fails.
# (Both original leaks — sanitize_thinking_blocks->langchain_anthropic and
# tool_error_handler->agent.server — were removed; the engine is now fully neutral.)
KNOWN_LEAKS: dict[str, set[str]] = {}


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (level > 0): those stay inside the engine.
            if node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
    return tops


@pytest.mark.parametrize(
    "py_file",
    sorted(ENGINE_ROOT.rglob("*.py")),
    ids=lambda p: str(p.relative_to(ENGINE_ROOT)),
)
def test_engine_core_stays_provider_and_domain_neutral(py_file: Path) -> None:
    rel = py_file.relative_to(ENGINE_ROOT).as_posix()
    allowed = KNOWN_LEAKS.get(rel, set())
    leaked = (_imported_top_levels(py_file) & FORBIDDEN_TOP_LEVEL) - allowed
    assert not leaked, (
        f"{rel} imports {sorted(leaked)}; "
        "engine-core must stay provider- and domain-neutral (receive resolved "
        "models/tools, never import provider SDKs or product layers)."
    )
