"""Unit tests for the devcontainer_worktree provider (fake CLI, no Docker).

Validates the argv this provider hands to the ``devcontainer`` CLI, that the
inherited guardrails still short-circuit dangerous commands before the CLI runs,
and that startup validation fails fast without Docker/the CLI.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from agent.integrations.devcontainer_worktree import (
    DevcontainerWorktreeBackend,
    _build_down_args,
    _build_exec_args,
    _build_up_args,
    _parse_container_id,
    validate_devcontainer_startup_config,
)

_MODULE = "agent.integrations.devcontainer_worktree"


def test_build_args_shape(tmp_path: Path) -> None:
    assert _build_up_args("devcontainer", tmp_path) == [
        "devcontainer", "up", "--workspace-folder", str(tmp_path),
    ]
    assert _build_exec_args("devcontainer", tmp_path, "ls -la") == [
        "devcontainer", "exec", "--workspace-folder", str(tmp_path), "bash", "-lc", "ls -la",
    ]
    assert _build_down_args("devcontainer", tmp_path) == [
        "devcontainer", "down", "--workspace-folder", str(tmp_path),
    ]


def test_parse_container_id() -> None:
    out = 'building...\n{"outcome":"success","containerId":"abc123","remoteUser":"node"}\n'
    assert _parse_container_id(out) == "abc123"
    assert _parse_container_id("no json here") is None


def test_up_runs_cli_and_parses_container(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], timeout: int | None) -> tuple[int, str]:
        calls.append(argv)
        return 0, '{"outcome":"success","containerId":"cid-1"}'

    with patch(f"{_MODULE}._run_capture", side_effect=fake_run):
        backend = DevcontainerWorktreeBackend(tmp_path, up=True)

    assert backend.container_id == "cid-1"
    assert calls[0] == _build_up_args("devcontainer", backend.root_dir)
    assert backend.id.startswith("devcontainer-worktree-")


def test_up_failure_raises(tmp_path: Path) -> None:
    with patch(f"{_MODULE}._run_capture", return_value=(1, "boom")):
        with pytest.raises(RuntimeError, match="devcontainer up.*failed"):
            DevcontainerWorktreeBackend(tmp_path, up=True)


def test_execute_dispatches_into_container(tmp_path: Path) -> None:
    backend = DevcontainerWorktreeBackend(tmp_path, up=False)
    recorded: dict = {}

    def fake_run(argv: list[str], timeout: int | None) -> tuple[int, str]:
        recorded["argv"] = argv
        recorded["timeout"] = timeout
        return 0, "/workspaces/x\n"

    with patch(f"{_MODULE}._run_capture", side_effect=fake_run):
        result = backend.execute("pwd")

    assert result.exit_code == 0
    assert result.output == "/workspaces/x\n"
    assert recorded["argv"] == _build_exec_args("devcontainer", backend.root_dir, "pwd")


def test_execute_blocks_dangerous_command_without_cli(tmp_path: Path) -> None:
    backend = DevcontainerWorktreeBackend(tmp_path, up=False)
    with patch(f"{_MODULE}._run_capture") as run:
        result = backend.execute("git push origin main")
    run.assert_not_called()
    assert result.exit_code == 126
    assert "blocked" in result.output.lower()


def test_execute_blocks_escape_executable(tmp_path: Path) -> None:
    backend = DevcontainerWorktreeBackend(tmp_path, up=False)
    with patch(f"{_MODULE}._run_capture") as run:
        result = backend.execute("ssh user@host 'echo hi'")
    run.assert_not_called()
    assert result.exit_code == 126
    assert "ssh" in result.output.lower()


def test_execute_allows_container_absolute_paths(tmp_path: Path) -> None:
    # Inside the container the box is the boundary: /etc and absolute paths are fine.
    backend = DevcontainerWorktreeBackend(tmp_path, up=False)
    with patch(f"{_MODULE}._run_capture", return_value=(0, "ubuntu")) as run:
        result = backend.execute("cat /etc/os-release")
    run.assert_called_once()
    assert result.exit_code == 0
    assert result.output == "ubuntu"


async def test_aexecute_dispatches(tmp_path: Path) -> None:
    backend = DevcontainerWorktreeBackend(tmp_path, up=False)

    async def fake_arun(argv: list[str], timeout: int | None) -> tuple[int, str]:
        return 0, "ok"

    with patch(f"{_MODULE}._arun_capture", side_effect=fake_arun):
        result = await backend.aexecute("ls")

    assert result.exit_code == 0
    assert result.output == "ok"


def test_validate_requires_devcontainer_cli() -> None:
    def which(name: str) -> str | None:
        return None if name == "devcontainer" else "/usr/bin/docker"

    with patch(f"{_MODULE}.shutil.which", side_effect=which):
        with pytest.raises(ValueError, match="devcontainer.*CLI"):
            validate_devcontainer_startup_config()


def test_validate_requires_docker_daemon() -> None:
    with patch(f"{_MODULE}.shutil.which", return_value="/usr/bin/x"), patch(
        f"{_MODULE}.subprocess.run"
    ) as run:
        run.return_value.returncode = 1
        with pytest.raises(ValueError, match="daemon"):
            validate_devcontainer_startup_config()
