"""TaskResolver — classify a developer request into one task kind via a mini LLM query.

A small, cheap model (the ON Model Gateway picks the provider) maps the user's
prompt to exactly one of the profile's ``task_kinds``. This is an *auxiliary*
signal that lets the ContextResolver and prompt tailor the run; it is not an
authority. If classification fails or is ambiguous, ``resolve_task_kind`` returns
``None`` and the run proceeds without a task framing (graceful degradation — not a
context fallback).

The model is configurable via ``ON_AGENT_TASK_FINDER_MODEL`` (a logical gateway
model id). Operators should point it at a small/cheap model; it defaults to the
gateway's default model so it always resolves.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

from model_launcher import DEFAULT_GATEWAY_MODEL, make_model

from .developer_profiles import TASK_KINDS

logger = logging.getLogger(__name__)

# Short glosses help a small model disambiguate. Keys must stay within TASK_KINDS.
TASK_KIND_DESCRIPTIONS: dict[str, str] = {
    "bug_analysis": "investigate/diagnose a defect or unexpected behavior",
    "requirement_analysis": "analyze a feature request, story, or requirement",
    "implementation": "write or change code to build a feature or fix",
    "testing_validation": "write or run tests / validate behavior in code",
    "mobile_device_validation": "validate the app on a real or emulated device",
    "work_item_update_proposal": "propose an update/comment to a work item or ticket",
    "release_risk_review": "assess release/merge risk of a change",
}

# Output cap for the classification call. Enough for a label (plus minor reasoning
# from a small model); large answers are unexpected and get parsed leniently.
_MAX_OUTPUT_TOKENS = 256


def _task_finder_model_id() -> str:
    return os.environ.get("ON_AGENT_TASK_FINDER_MODEL", "").strip() or DEFAULT_GATEWAY_MODEL


def _classification_prompt(user_text: str, kinds: Sequence[str]) -> str:
    options = "\n".join(
        f"- {kind}: {TASK_KIND_DESCRIPTIONS.get(kind, kind)}" for kind in kinds
    )
    return (
        "You are a task classifier for a software-engineering agent. Classify the "
        "developer's request below into exactly ONE of these task kinds:\n"
        f"{options}\n\n"
        "Respond with ONLY the task kind id (e.g. `implementation`), nothing else.\n\n"
        "Request:\n"
        f"{user_text}"
    )


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return " ".join(parts)
    return str(content or "")


def _clean_label(raw: str) -> str:
    """Reduce a model response to a bare label candidate.

    Reasoning models sometimes preface the answer, so the label is taken from the
    last non-empty line and stripped of quotes/backticks/trailing punctuation.
    """
    text = (raw or "").strip()
    if "\n" in text:
        lines = [line for line in text.splitlines() if line.strip()]
        text = lines[-1] if lines else ""
    # Strip surrounding whitespace, quotes, backticks and trailing punctuation at once.
    return text.strip(" \t`'\".:").lower()


def _match_kind(raw: str, kinds: Sequence[str]) -> str | None:
    # Strict exact match (no "contained substring": that misclassifies sentences like
    # "esto no es implementation"). The prompt asks for only the label.
    cleaned = _clean_label(raw)
    if not cleaned:
        return None
    for kind in kinds:
        if kind.lower() == cleaned:
            return kind
    return None


async def resolve_task_kind(
    user_text: str,
    task_kinds: Sequence[str] = TASK_KINDS,
    *,
    model_id: str | None = None,
) -> str | None:
    """Classify ``user_text`` into one of ``task_kinds`` (or ``None`` if unclear)."""
    text = (user_text or "").strip()
    if not text:
        return None
    kinds = tuple(task_kinds) or TASK_KINDS

    resolved_model = model_id or _task_finder_model_id()
    try:
        model = make_model(resolved_model, max_tokens=_MAX_OUTPUT_TOKENS, temperature=0.0)
        response = await model.ainvoke(_classification_prompt(text, kinds))
        raw = _response_text(response)
    except Exception:
        logger.warning(
            "Task finder failed (model=%s); proceeding without task_kind",
            resolved_model,
            exc_info=True,
        )
        return None

    kind = _match_kind(raw, kinds)
    if kind is None:
        logger.info("Task finder produced no matching task_kind (raw=%r)", raw[:120])
    return kind
