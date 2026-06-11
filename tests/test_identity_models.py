from agent.identity.models import AuthenticatedUser, user_from_actor_id


def test_authenticated_user_builds_provider_neutral_metadata() -> None:
    user = AuthenticatedUser(
        provider="github", subject_id="octocat", email="Octo@Example.COM", display_name="OctoCat"
    )

    assert user.actor_id == "github:octocat"
    assert user.metadata() == {
        "actor_id": "github:octocat",
        "auth_provider": "github",
        "actor_email": "octo@example.com",
        "actor_display_name": "OctoCat",
    }


def test_user_from_actor_id_preserves_provider() -> None:
    user = user_from_actor_id("entra:user-oid", email="Dev@Example.COM")

    assert user.provider == "entra"
    assert user.subject_id == "user-oid"
    assert user.actor_id == "entra:user-oid"
    assert user.normalized_email == "dev@example.com"
