"""Enforce the DeveloperProfile's project/repo scope on resolved tools.

Entra bounds what the actor can access (the ADO token is the actor's own); this
guard fences a run to the profile's *focus* within that access: a tool call that
carries a project/repo argument outside the profile's effective scope is blocked
and audited instead of executed. Tools with no project/repo argument (org-wide
reads) pass through unchanged.

This turns ``allowed_projects``/``allowed_repos`` from prompt-only hints into real
enforcement, without changing the Capability Gateway contract — composition owns
the profile, so the profile boundary is applied here.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

# Argument keys that carry a project/repo *name* (id-only keys are not name-checkable
# against the profile's names, so they're skipped — see ``_looks_like_id``).
_PROJECT_ARG_KEYS = {"project", "projectname", "projectnameorid"}
_REPO_ARG_KEYS = {"repository", "repositoryname", "repositorynameorid", "repo", "reponameorid"}

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _looks_like_id(value: str) -> bool:
    """A GUID can't be validated against profile *names*; let it through."""
    return bool(_GUID.match(value.strip()))


def _scope_violation(
    kwargs: dict[str, Any],
    allowed_projects: frozenset[str],
    allowed_repos: frozenset[str],
) -> str | None:
    for key, value in kwargs.items():
        if not isinstance(value, str) or not value.strip() or _looks_like_id(value):
            continue
        normalized_key = key.strip().casefold()
        normalized_value = value.strip().casefold()
        if allowed_projects and normalized_key in _PROJECT_ARG_KEYS:
            if normalized_value not in allowed_projects:
                return f"project '{value}'"
        if allowed_repos and normalized_key in _REPO_ARG_KEYS:
            if normalized_value not in allowed_repos:
                return f"repository '{value}'"
    return None


def _guard_tool(
    tool: BaseTool,
    allowed_projects: frozenset[str],
    allowed_repos: frozenset[str],
    projects_label: str,
) -> BaseTool:
    def _blocked(what: str) -> str:
        logger.info("scope guard blocked tool=%s outside profile: %s", tool.name, what)
        return (
            f"Blocked: {what} is outside this run's DeveloperProfile scope "
            f"(allowed projects: {projects_label}). Use an in-scope project/repository, "
            "or ask the user to widen the profile."
        )

    async def _arun(**kwargs: Any) -> Any:
        violation = _scope_violation(kwargs, allowed_projects, allowed_repos)
        return _blocked(violation) if violation else await tool.ainvoke(kwargs)

    def _run(**kwargs: Any) -> Any:
        violation = _scope_violation(kwargs, allowed_projects, allowed_repos)
        return _blocked(violation) if violation else tool.invoke(kwargs)

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=tool.name,
        description=tool.description or "",
        args_schema=getattr(tool, "args_schema", None),
        metadata=getattr(tool, "metadata", None),
    )


def enforce_profile_scope(
    tools: Sequence[BaseTool],
    *,
    allowed_projects: Sequence[str],
    allowed_repos: Sequence[str] = (),
) -> list[BaseTool]:
    """Wrap ``tools`` so calls outside the profile's project/repo scope are blocked.

    No-op (returns the tools unchanged) when there is nothing to enforce.
    """
    projects = frozenset(p.strip().casefold() for p in allowed_projects if p.strip())
    repos = frozenset(r.strip().casefold() for r in allowed_repos if r.strip())
    if not projects and not repos:
        return list(tools)
    projects_label = ", ".join(allowed_projects) or "<none>"
    return [_guard_tool(tool, projects, repos, projects_label) for tool in tools]
