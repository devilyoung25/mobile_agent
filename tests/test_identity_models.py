from agent.identity.models import github_user, user_from_actor_id


def test_github_user_builds_provider_neutral_metadata() -> None:
    user = github_user("OctoCat", email="Octo@Example.COM")

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
