from __future__ import annotations

import pytest

from agent.composition.developer_profiles import (
    DeveloperProfile,
    developer_profiles,
)
from agent.composition.profile_resolution import (
    ProfileResolutionError,
    resolve_developer_profile,
)


def _profile(**overrides: object) -> DeveloperProfile:
    base = {
        "id": "p",
        "label": "P",
        "business_line": "bl",
        "allowed_projects": ("Proj A", "Proj B"),
    }
    base.update(overrides)
    return DeveloperProfile(**base)  # type: ignore[arg-type]


# ---- DeveloperProfile.matches_scope / effective_scope ----


def test_matches_scope_is_case_insensitive_and_intersects() -> None:
    profile = _profile()
    assert profile.matches_scope(["proj a"]) is True
    assert profile.matches_scope(["PROJ B", "Other"]) is True
    assert profile.matches_scope(["Unrelated"]) is False
    assert profile.matches_scope([]) is False


def test_matches_scope_false_when_no_allowed_projects() -> None:
    # An empty allowed_projects must NOT act as a catch-all (no fallback).
    assert _profile(allowed_projects=()).matches_scope(["anything"]) is False


def test_effective_scope_intersects_preserving_actor_order() -> None:
    profile = _profile()
    actor_scope = ["Other", "proj b", "Proj A"]
    assert profile.effective_scope(actor_scope) == ["proj b", "Proj A"]


def test_effective_scope_empty_when_no_overlap() -> None:
    assert _profile().effective_scope(["X", "Y"]) == []


# ---- resolve_developer_profile ----


def test_resolve_returns_matching_profile() -> None:
    # The actor can see the TryController 2.0 project -> mobile profile (env-driven).
    profile = resolve_developer_profile("entra:dev", ["TryController 2.0"])
    assert profile.id == "trycontroller_android"
    assert profile.domain_pack == "mobile"
    assert profile.business_line == "trycontroller"


def test_resolve_matches_any_declared_project() -> None:
    profile = resolve_developer_profile("entra:dev", ["VendaMas 2.0", "Foo"])
    assert profile.id == "trycontroller_android"
    assert profile.effective_scope(["VendaMas 2.0", "Foo"]) == ["VendaMas 2.0"]


def test_resolve_raises_without_match() -> None:
    with pytest.raises(ProfileResolutionError):
        resolve_developer_profile("entra:dev", ["SomeOtherTeamProject"])


def test_resolve_raises_on_empty_scope() -> None:
    with pytest.raises(ProfileResolutionError):
        resolve_developer_profile(None, [])


def test_registry_has_the_mobile_profile() -> None:
    profiles = developer_profiles()
    assert any(p.id == "trycontroller_android" for p in profiles)
    assert all(p.allowed_projects for p in profiles)  # no catch-all profiles
