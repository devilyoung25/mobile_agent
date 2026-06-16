"""Developer/Product profiles — the operating world of the agent per team/stack.

A :class:`DeveloperProfile` describes everything composition needs to scope and
contextualize a run for a development team: the Azure DevOps projects/repos it
operates on, the integration branch, the technical stack, the supported task
kinds, and short operating rules.

Entra remains the authority: the profile only *narrows* the actor's existing
access (``resolve_actor_scope``) and *adds* context — it never grants access.

Defined as constants (no DB). The product targets the mobile team, so there is a
single profile today (TryController Android). The business line is derived from
the Azure DevOps projects the actor can access.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

# Task kinds the agent can classify a request into (consumed by the TaskResolver,
# PR2). Kept here so a profile can declare the subset it supports.
TASK_KINDS: tuple[str, ...] = (
    "bug_analysis",
    "requirement_analysis",
    "implementation",
    "testing_validation",
    "mobile_device_validation",
    "work_item_update_proposal",
    "release_risk_review",
)


class DeveloperProfile(BaseModel):
    """Operating context for a development team/stack. Immutable (frozen)."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    business_line: str
    # Scoping / narrowing (Entra is the authority; the match is done against these).
    azure_devops_org: str | None = None
    allowed_projects: tuple[str, ...] = ()
    allowed_repos: tuple[str, ...] = ()
    integration_branch: str = "develop"
    # Technical / business context (feeds ContextResolver + prompt in later PRs).
    stack: str = ""
    context_providers: tuple[str, ...] = ()
    technical_notes: tuple[str, ...] = ()
    business_knowledge_indexes: tuple[str, ...] = ()
    # Capabilities.
    domain_pack: str = "mobile"
    # Tasks.
    task_kinds: tuple[str, ...] = TASK_KINDS
    # Short operating rules injected into the prompt.
    operating_rules: tuple[str, ...] = ()

    def matches_scope(self, actor_scope: Sequence[str]) -> bool:
        """True when the actor can access at least one of the profile's projects."""
        if not self.allowed_projects:
            return False
        scope = {p.strip().casefold() for p in actor_scope}
        return any(p.strip().casefold() in scope for p in self.allowed_projects)

    def effective_scope(self, actor_scope: Sequence[str]) -> list[str]:
        """The profile's projects intersected with what the actor can access.

        Preserves the order reported by ``actor_scope``.
        """
        allowed = {p.strip().casefold() for p in self.allowed_projects}
        return [p for p in actor_scope if p.strip().casefold() in allowed]


def _env_list(name: str) -> tuple[str, ...]:
    """Parse a comma-separated env var into a tuple of trimmed values."""
    return tuple(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())


def _trycontroller_android_profile() -> DeveloperProfile:
    """Mobile/TryController profile.

    Deployment-specific Azure DevOps scope lives in ``.env`` (not in code):
    - ``AZURE_DEVOPS_MCP_ORG`` — the org (shared with ``resolve_actor_scope``).
    - ``ON_DEVPROFILE_TRYCONTROLLER_PROJECTS`` — comma-separated ADO project names;
      these drive profile matching (e.g. ``TryController 2.0,VendaMas 2.0``).
    - ``ON_DEVPROFILE_TRYCONTROLLER_REPOS`` — comma-separated repo names (context).
    - ``ON_DEVPROFILE_TRYCONTROLLER_INTEGRATION_BRANCH`` — integration branch
      (default ``develop``; AppMóvil uses ``dev``).
    """
    integration_branch = (
        os.environ.get("ON_DEVPROFILE_TRYCONTROLLER_INTEGRATION_BRANCH", "develop").strip()
        or "develop"
    )
    return DeveloperProfile(
        id="trycontroller_android",
        label="Desarrollador móvil — TryController (Android)",
        business_line="trycontroller",
        azure_devops_org=os.environ.get("AZURE_DEVOPS_MCP_ORG", "").strip() or None,
        allowed_projects=_env_list("ON_DEVPROFILE_TRYCONTROLLER_PROJECTS"),
        allowed_repos=_env_list("ON_DEVPROFILE_TRYCONTROLLER_REPOS"),
        integration_branch=integration_branch,
        stack="android-kotlin",
        context_providers=("azure-devops",),
        technical_notes=(
            "Aplicación Android nativa en Kotlin.",
            f"Rama de integración: {integration_branch}.",
        ),
        domain_pack="mobile",
        task_kinds=TASK_KINDS,
        operating_rules=(
            "Trabaja únicamente dentro de los repos/proyectos del perfil.",
            "Azure DevOps es read-only; toda acción persistente requiere aprobación humana.",
        ),
    )


def developer_profiles() -> tuple[DeveloperProfile, ...]:
    """The configured developer profiles (Azure DevOps scope read from env).

    One profile today (mobile team). Read at call time so ``.env`` changes apply
    without code edits and tests can set the scope via env; more business lines
    are added here, each declaring the projects that identify it.
    """
    return (_trycontroller_android_profile(),)
