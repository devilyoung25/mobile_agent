from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.composition.task_resolution import resolve_task_kind


class _FakeModel:
    def __init__(self, content: object) -> None:
        self._content = content

    async def ainvoke(self, _prompt: object) -> SimpleNamespace:
        return SimpleNamespace(content=self._content)


def _patch_model(content: object):
    return patch("agent.composition.task_resolution.make_model", return_value=_FakeModel(content))


async def test_classifies_exact_label() -> None:
    with _patch_model("implementation"):
        assert await resolve_task_kind("add a new settings screen") == "implementation"


async def test_classifies_label_with_formatting() -> None:
    # Quotes/backticks/trailing period around a bare label still match.
    with _patch_model("`implementation`."):
        assert await resolve_task_kind("add a settings screen") == "implementation"


async def test_uses_last_line_for_reasoning_models() -> None:
    with _patch_model("Let me think about this...\ntesting_validation"):
        assert await resolve_task_kind("add unit tests") == "testing_validation"


async def test_sentence_containing_label_is_rejected() -> None:
    # A full sentence is not a label: strict match avoids the "no es implementation" bug.
    with _patch_model("esto no es implementation"):
        assert await resolve_task_kind("algo") is None


async def test_classifies_from_list_content() -> None:
    with _patch_model([{"type": "text", "text": "testing_validation"}]):
        assert await resolve_task_kind("add unit tests for the cart") == "testing_validation"


async def test_invalid_label_returns_none() -> None:
    with _patch_model("totally-not-a-kind"):
        assert await resolve_task_kind("whatever") is None


async def test_empty_text_skips_model() -> None:
    model_factory = MagicMock()
    with patch("agent.composition.task_resolution.make_model", model_factory):
        assert await resolve_task_kind("   ") is None
    model_factory.assert_not_called()


async def test_model_error_degrades_to_none() -> None:
    with patch(
        "agent.composition.task_resolution.make_model", side_effect=RuntimeError("boom")
    ):
        assert await resolve_task_kind("do something") is None


async def test_respects_restricted_task_kinds() -> None:
    # A kind outside the profile's supported subset is not returned.
    with _patch_model("release_risk_review"):
        assert await resolve_task_kind("ship it?", task_kinds=("implementation",)) is None
