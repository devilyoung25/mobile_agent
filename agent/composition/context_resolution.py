"""ContextResolver — assemble the compact operating context for a run.

Given the resolved :class:`DeveloperProfile`, the classified ``task_kind``, and
the actor's Azure DevOps scope, build a small, task-aware context block that
composition injects into the prompt (PR4). Today it is assembled from the profile
constants. The :class:`ContextProvider` seam lets future MCP-backed providers — a
Developer MCP and a Knowledge MCP (business logic + technical/architecture) —
contribute sections without changing the resolver or the neutral engine. Context
is read-only: a provider never authorizes anything.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .developer_profiles import DeveloperProfile

logger = logging.getLogger(__name__)

# One-line focus per task kind — orients the agent for the task at hand.
TASK_KIND_FOCUS: dict[str, str] = {
    "bug_analysis": "Diagnose the root cause from code and context before proposing a change.",
    "requirement_analysis": "Clarify scope and acceptance criteria; map the request to the codebase.",
    "implementation": "Make the change cohesively with the surrounding code; keep it minimal.",
    "testing_validation": "Add or run tests; validate behavior and edge cases.",
    "mobile_device_validation": "Validate on a device/emulator; capture evidence (screens/elements).",
    "work_item_update_proposal": "Draft the work-item update/comment; do not persist without approval.",
    "release_risk_review": "Assess merge/release risk: blast radius, migrations, rollback.",
}


@runtime_checkable
class ContextProvider(Protocol):
    """A source that contributes a rendered context section for a run.

    Future Developer MCP / Knowledge MCP integrations implement this; the
    resolver awaits each and appends non-empty sections.
    """

    name: str

    async def contribute(
        self,
        *,
        profile: DeveloperProfile,
        task_kind: str | None,
        actor_scope: Sequence[str],
    ) -> str | None: ...


@dataclass(frozen=True)
class OperatingContext:
    """Compact, task-aware operating context for a run."""

    profile_id: str
    profile_label: str
    business_line: str
    stack: str
    integration_branch: str
    project_scope: tuple[str, ...]
    task_kind: str | None
    task_focus: str | None
    technical_notes: tuple[str, ...]
    operating_rules: tuple[str, ...]
    provider_sections: tuple[str, ...] = ()

    def render(self) -> str:
        """Render the context as neutral prompt text (no brand-specific assumptions)."""
        lines: list[str] = ["## Operating context"]
        lines.append(
            f"- Profile: {self.profile_label} "
            f"(`{self.profile_id}`, business line `{self.business_line}`)."
        )
        if self.stack:
            lines.append(f"- Stack: {self.stack}.")
        if self.project_scope:
            lines.append(f"- Projects in scope: {', '.join(self.project_scope)}.")
        lines.append(f"- Integration branch: {self.integration_branch}.")
        if self.task_kind:
            focus = f" — {self.task_focus}" if self.task_focus else ""
            lines.append(f"- Task kind: {self.task_kind}{focus}")
        if self.technical_notes:
            lines.append("- Technical notes:")
            lines.extend(f"  - {note}" for note in self.technical_notes)
        if self.operating_rules:
            lines.append("- Operating rules:")
            lines.extend(f"  - {rule}" for rule in self.operating_rules)
        for section in self.provider_sections:
            if section.strip():
                lines.append(section.strip())
        return "\n".join(lines)


async def resolve_operating_context(
    profile: DeveloperProfile,
    task_kind: str | None,
    actor_scope: Sequence[str],
    *,
    providers: Sequence[ContextProvider] = (),
) -> OperatingContext:
    """Build the operating context from the profile, task kind, and actor scope.

    ``task_kind`` is honored only when the profile supports it. Each provider in
    ``providers`` may contribute a section; a failing provider is skipped so the
    run still gets the constants-based context.
    """
    effective_task_kind = (
        task_kind if (task_kind and task_kind in profile.task_kinds) else None
    )

    sections: list[str] = []
    for provider in providers:
        try:
            section = await provider.contribute(
                profile=profile,
                task_kind=effective_task_kind,
                actor_scope=actor_scope,
            )
        except Exception:
            logger.warning(
                "Context provider %s failed", getattr(provider, "name", "?"), exc_info=True
            )
            continue
        if isinstance(section, str) and section.strip():
            sections.append(section.strip())

    return OperatingContext(
        profile_id=profile.id,
        profile_label=profile.label,
        business_line=profile.business_line,
        stack=profile.stack,
        integration_branch=profile.integration_branch,
        project_scope=tuple(profile.effective_scope(actor_scope)),
        task_kind=effective_task_kind,
        task_focus=TASK_KIND_FOCUS.get(effective_task_kind) if effective_task_kind else None,
        technical_notes=profile.technical_notes,
        operating_rules=profile.operating_rules,
        provider_sections=tuple(sections),
    )
