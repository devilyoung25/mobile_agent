"""Built-in context providers for DeveloperProfile operating context.

These providers are intentionally static and read-only. They exercise the
ContextProvider seam without introducing Knowledge MCP/RAG yet.
"""

from __future__ import annotations

from collections.abc import Sequence

from .context_resolution import ContextProvider
from .developer_profiles import DeveloperProfile


class AndroidEngineeringContextProvider:
    """Compact Android/Kotlin guidance for mobile engineering runs."""

    name = "android-engineering"

    async def contribute(
        self,
        *,
        profile: DeveloperProfile,
        task_kind: str | None,
        actor_scope: Sequence[str],
    ) -> str | None:
        if "android" not in profile.stack.casefold():
            return None
        lines = [
            "## Android engineering context",
            "- Prefer the app's existing Kotlin, Gradle, DI, navigation, and testing conventions.",
            "- Validate code changes with the narrowest useful Gradle task before broad tests.",
            "- For UI/navigation bugs, collect device/emulator evidence before claiming the fix is done.",
            "- Treat ADB/emulator/QA execution as controlled runner work, not arbitrary shell exploration.",
        ]
        if task_kind == "mobile_device_validation":
            lines.append("- Required evidence: device/emulator result, screenshot or UI-tree signal, and relevant logs.")
        return "\n".join(lines)


class BusinessKnowledgePlaceholderProvider:
    """Placeholder until Business Knowledge MCP/RAG is wired."""

    name = "business-knowledge"

    async def contribute(
        self,
        *,
        profile: DeveloperProfile,
        task_kind: str | None,
        actor_scope: Sequence[str],
    ) -> str | None:
        if not profile.business_knowledge_indexes:
            return None
        indexes = ", ".join(profile.business_knowledge_indexes)
        return (
            "## Business knowledge context\n"
            f"- Curated indexes configured for this profile: {indexes}.\n"
            "- Knowledge lookup is not connected in this build; ask for missing product rules instead of inventing them."
        )


def context_providers_for_profile(profile: DeveloperProfile) -> tuple[ContextProvider, ...]:
    """Return internal providers enabled for ``profile``.

    The profile declares provider names, but Android guidance is also enabled by
    stack so the current mobile profile gets guidance without a new static field.
    """
    provider_names = {name.strip().casefold() for name in profile.context_providers}
    providers: list[ContextProvider] = []
    if "android-engineering" in provider_names or "android" in profile.stack.casefold():
        providers.append(AndroidEngineeringContextProvider())
    if profile.business_knowledge_indexes or "business-knowledge" in provider_names:
        providers.append(BusinessKnowledgePlaceholderProvider())
    return tuple(providers)
