from __future__ import annotations

from collections.abc import Sequence

from agent.composition.context_resolution import (
    OperatingContext,
    resolve_operating_context,
)
from agent.composition.developer_profiles import DeveloperProfile


def _profile(**overrides: object) -> DeveloperProfile:
    base: dict[str, object] = {
        "id": "trycontroller_android",
        "label": "Móvil TryController",
        "business_line": "trycontroller",
        "allowed_projects": ("AppMovil", "VendaMas 2.0"),
        "stack": "android-kotlin",
        "technical_notes": ("Kotlin nativo.",),
        "operating_rules": ("Solo repos del perfil.",),
        "task_kinds": ("implementation", "bug_analysis"),
    }
    base.update(overrides)
    return DeveloperProfile(**base)  # type: ignore[arg-type]


class _StaticProvider:
    name = "knowledge-mcp"

    def __init__(self, section: str | None) -> None:
        self._section = section

    async def contribute(
        self,
        *,
        profile: DeveloperProfile,
        task_kind: str | None,
        actor_scope: Sequence[str],
    ) -> str | None:
        return self._section


class _BoomProvider:
    name = "developer-mcp"

    async def contribute(self, **_kwargs: object) -> str | None:
        raise RuntimeError("provider down")


async def test_intersects_scope_and_keeps_supported_task_kind() -> None:
    ctx = await resolve_operating_context(
        _profile(), "implementation", ["AppMovil", "OtherTeam"]
    )
    assert ctx.project_scope == ("AppMovil",)
    assert ctx.task_kind == "implementation"
    assert ctx.task_focus is not None
    assert ctx.stack == "android-kotlin"


async def test_task_kind_outside_profile_is_dropped() -> None:
    ctx = await resolve_operating_context(_profile(), "release_risk_review", ["AppMovil"])
    assert ctx.task_kind is None
    assert ctx.task_focus is None


async def test_none_task_kind_is_fine() -> None:
    ctx = await resolve_operating_context(_profile(), None, ["AppMovil"])
    assert ctx.task_kind is None


async def test_provider_section_is_included_and_failure_is_skipped() -> None:
    ctx = await resolve_operating_context(
        _profile(),
        "bug_analysis",
        ["AppMovil"],
        providers=[_BoomProvider(), _StaticProvider("### Knowledge\nPayments domain.")],
    )
    assert any("Payments domain." in s for s in ctx.provider_sections)
    assert len(ctx.provider_sections) == 1  # the failing provider was skipped


async def test_render_includes_key_sections() -> None:
    ctx = await resolve_operating_context(
        _profile(),
        "implementation",
        ["AppMovil"],
        providers=[_StaticProvider("### Knowledge\nDomain notes.")],
    )
    rendered = ctx.render()
    assert "Operating context" in rendered
    assert "android-kotlin" in rendered
    assert "AppMovil" in rendered
    assert "Task kind: implementation" in rendered
    assert "Solo repos del perfil." in rendered
    assert "Domain notes." in rendered


def test_render_is_synchronous_on_dataclass() -> None:
    ctx = OperatingContext(
        profile_id="p",
        profile_label="P",
        business_line="bl",
        stack="",
        integration_branch="develop",
        project_scope=(),
        task_kind=None,
        task_focus=None,
        technical_notes=(),
        operating_rules=(),
    )
    assert ctx.render().startswith("## Operating context")
