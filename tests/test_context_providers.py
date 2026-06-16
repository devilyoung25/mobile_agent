from __future__ import annotations

from agent.composition.context_providers import context_providers_for_profile
from agent.composition.developer_profiles import DeveloperProfile


def _profile(**overrides: object) -> DeveloperProfile:
    base: dict[str, object] = {
        "id": "trycontroller_android",
        "label": "Móvil TryController",
        "business_line": "trycontroller",
        "allowed_projects": ("TryController 2.0",),
        "stack": "android-kotlin",
    }
    base.update(overrides)
    return DeveloperProfile(**base)  # type: ignore[arg-type]


async def test_android_provider_contributes_for_android_stack() -> None:
    [provider] = context_providers_for_profile(_profile())

    section = await provider.contribute(
        profile=_profile(),
        task_kind="implementation",
        actor_scope=["TryController 2.0"],
    )

    assert section is not None
    assert "Android engineering context" in section
    assert "Gradle" in section


async def test_android_provider_adds_device_evidence_for_mobile_validation() -> None:
    [provider] = context_providers_for_profile(_profile())

    section = await provider.contribute(
        profile=_profile(),
        task_kind="mobile_device_validation",
        actor_scope=["TryController 2.0"],
    )

    assert section is not None
    assert "Required evidence" in section


async def test_business_placeholder_contributes_only_when_indexes_exist() -> None:
    providers = context_providers_for_profile(
        _profile(stack="dotnet", business_knowledge_indexes=("trycontroller-rules",))
    )

    assert [provider.name for provider in providers] == ["business-knowledge"]
    section = await providers[0].contribute(
        profile=_profile(stack="dotnet", business_knowledge_indexes=("trycontroller-rules",)),
        task_kind=None,
        actor_scope=["TryController 2.0"],
    )

    assert section is not None
    assert "trycontroller-rules" in section
    assert "not connected" in section


def test_non_android_profile_without_indexes_has_no_providers() -> None:
    assert context_providers_for_profile(_profile(stack="dotnet")) == ()
