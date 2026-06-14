from unittest.mock import MagicMock, patch

import pytest
from model_launcher import (
    create_model_plan,
    default_model_pair,
    make_model,
    model_supports_effort,
    supported_model_ids,
    supported_models,
)


def test_registry_exposes_only_logical_gateway_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "")

    models = supported_models()

    assert models == [
        {
            "id": "on-auto-coder",
            "label": "on-auto-coder",
            "efforts": ["medium"],
            "default_effort": "medium",
            "supports_images": False,
        }
    ]
    assert supported_model_ids() == frozenset({"on-auto-coder"})


def test_registry_can_list_extra_logical_gateway_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    monkeypatch.setenv("MODEL_GATEWAY_MODELS", "on-fast,on-deep")
    monkeypatch.setenv(
        "MODEL_GATEWAY_MODEL_LABELS",
        "on-auto-coder=Auto Coder,on-fast=Fast,on-deep=Deep",
    )

    assert [m["id"] for m in supported_models()] == ["on-auto-coder", "on-fast", "on-deep"]
    assert [m["label"] for m in supported_models()] == ["Auto Coder", "Fast", "Deep"]


def test_default_model_pair_uses_gateway_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_MODEL", "on-auto-coder")
    assert default_model_pair() == ("on-auto-coder", "medium")


def test_gateway_model_supports_configured_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_EFFORTS", "medium,high")
    assert model_supports_effort("on-auto-coder", "medium") is True
    assert model_supports_effort("on-auto-coder", "high") is True
    assert model_supports_effort("on-auto-coder", "max") is False


def test_make_model_requires_gateway_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_GATEWAY_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="MODEL_GATEWAY_BASE_URL is required"):
        make_model("on-auto-coder")


def test_make_model_uses_openai_compatible_gateway_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "gateway-key")
    monkeypatch.setenv("MODEL_GATEWAY_TEMPERATURE", "0.2")
    monkeypatch.setenv("MODEL_GATEWAY_MAX_TOKENS", "1234")
    model = MagicMock(name="gateway_model")

    with patch("langchain_openai.ChatOpenAI", return_value=model) as chat_openai:
        assert make_model("on-auto-coder", max_tokens=64_000) is model

    # Precedence: an explicit max_tokens arg wins over the env default (1234).
    chat_openai.assert_called_once_with(
        model="on-auto-coder",
        api_key="gateway-key",
        base_url="http://gateway.test/v1",
        temperature=0.2,
        max_tokens=64_000,
    )


def test_make_model_env_max_tokens_used_when_no_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("MODEL_GATEWAY_MAX_TOKENS", "1234")
    model = MagicMock(name="gateway_model")

    with patch("langchain_openai.ChatOpenAI", return_value=model) as chat_openai:
        make_model("on-auto-coder")

    assert chat_openai.call_args.kwargs["max_tokens"] == 1234


def test_make_model_applies_profile_effort_and_output_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setenv("MODEL_GATEWAY_MAX_TOKENS", "1234")
    captured: dict[str, object] = {}

    class _FakeChat:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    with patch("langchain_openai.ChatOpenAI", _FakeChat):
        make_model(
            "on-auto-coder",
            profile={"max_input_tokens": 200000},
            reasoning_effort="high",
            max_output_tokens=8000,
        )

    assert captured["profile"] == {"max_input_tokens": 200000}
    assert captured["reasoning_effort"] == "high"
    # Gateway-provided output cap wins over the env fallback (1234).
    assert captured["max_tokens"] == 8000


def test_profile_enables_fraction_based_summarization(monkeypatch: pytest.MonkeyPatch) -> None:
    # The core compaction fix: a model profile with max_input_tokens makes deepagents
    # trigger summarization at a fraction of the real window instead of a fixed count.
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    from deepagents.middleware.summarization import compute_summarization_defaults

    model = make_model("on-auto-coder", profile={"max_input_tokens": 200000})

    assert compute_summarization_defaults(model)["trigger"] == ("fraction", 0.85)


def test_no_profile_falls_back_to_fixed_summarization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "http://gateway.test/v1")
    from deepagents.middleware.summarization import compute_summarization_defaults

    model = make_model("on-auto-coder")

    assert compute_summarization_defaults(model)["trigger"] == ("tokens", 170000)


def test_model_plan_uses_gateway_main_and_subagent_models() -> None:
    main = MagicMock(name="main")
    subagent = MagicMock(name="subagent")

    def fake_make_model(model_id: str, **_kwargs: object) -> MagicMock:
        return {"on-auto-coder": main, "on-auto-subagent": subagent}[model_id]

    with patch("model_launcher.client.make_model", side_effect=fake_make_model):
        plan = create_model_plan(
            model_id="on-auto-coder",
            effort="medium",
            subagent_model_id="on-auto-subagent",
            subagent_effort="medium",
            max_tokens=64_000,
        )

    assert plan.model is main
    assert plan.subagent_model is subagent
    assert plan.model_id == "on-auto-coder"
    assert plan.effort == "medium"


def test_default_catalog_does_not_expose_provider_ids() -> None:
    provider_prefixes = ("ollama:", "openrouter:", "anthropic:", "openai:", "google_genai:")
    assert all(not model_id.startswith(provider_prefixes) for model_id in supported_model_ids())
