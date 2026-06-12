"""Allow/deny policy for tools exposed by an MCP server."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolPolicy:
    """Name-based gate deciding which MCP tools reach the agent.

    ``prefix`` scopes the policy: tools outside the prefix are dropped (they
    belong to another server or are unexpected). Within the prefix, a tool is
    allowed when its name contains any ``allow_markers`` substring or ends
    with any ``allow_suffixes`` entry — unless it matches ``deny_markers``,
    which always wins.
    """

    prefix: str = ""
    allow_names: tuple[str, ...] = ()
    allow_markers: tuple[str, ...] = ()
    allow_suffixes: tuple[str, ...] = ()
    deny_names: tuple[str, ...] = ()
    deny_markers: tuple[str, ...] = ()

    def allows(self, name: str) -> bool:
        normalized = name.strip().lower()
        if any(denied == normalized for denied in self.deny_names):
            return False
        if self.prefix and not normalized.startswith(self.prefix):
            return normalized in self.allow_names
        if any(marker in normalized for marker in self.deny_markers):
            return False
        if any(allowed == normalized for allowed in self.allow_names):
            return True
        if not self.allow_markers and not self.allow_suffixes:
            return True
        return any(marker in normalized for marker in self.allow_markers) or (
            bool(self.allow_suffixes) and normalized.endswith(self.allow_suffixes)
        )


READ_ONLY_POLICY_MARKERS: tuple[str, ...] = ("_list_", "_get_", "_search_", "_query_", "_show_")


@dataclass(frozen=True)
class FilterResult:
    allowed: list[Any] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


def filter_tools(tools: Sequence[Any], policy: ToolPolicy | None) -> FilterResult:
    """Split tools into allowed/blocked according to ``policy`` (None = allow all)."""
    if policy is None:
        return FilterResult(allowed=list(tools))
    result = FilterResult()
    for tool in tools:
        name = getattr(tool, "name", "")
        if not isinstance(name, str):
            continue
        if policy.allows(name):
            result.allowed.append(tool)
        elif not policy.prefix or name.strip().lower().startswith(policy.prefix):
            result.blocked.append(name)
    return result
