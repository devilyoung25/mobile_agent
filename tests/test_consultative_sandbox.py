"""Consultative (no-workspace) runs must not root the sandbox at the host project.

Guards bug #3: a free chat used to get a host shell rooted at the process cwd (the
ON Mobile Agent repo), so it explored the wrong project. Consultative runs now bind
to an isolated, empty scratch dir.
"""

import os

import pytest

from agent.composition.sandbox_resolution import _consultative_scratch_dir


def test_consultative_scratch_dir_is_isolated_empty_and_not_cwd(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_CONSULTATIVE_ROOT", str(tmp_path))
    path = _consultative_scratch_dir("019ec258-37ae-759b-a8d0-452e79c6a386")

    assert os.path.isdir(path)
    assert os.listdir(path) == []  # empty: nothing of the host project is visible
    assert os.path.abspath(path) != os.path.abspath(os.getcwd())
    assert str(tmp_path) in os.path.abspath(path)


def test_consultative_scratch_dir_sanitizes_thread_id(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_CONSULTATIVE_ROOT", str(tmp_path))
    path = _consultative_scratch_dir("../../etc/evil")
    # Path traversal in the thread id must not escape the scratch root.
    assert os.path.commonpath([os.path.abspath(path), os.path.abspath(tmp_path)]) == os.path.abspath(
        tmp_path
    )
