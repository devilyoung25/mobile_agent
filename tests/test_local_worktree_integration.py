from pathlib import Path

import pytest
from agent.integrations.local_worktree import (
    LocalWorktreeBackend,
    create_local_worktree_sandbox,
)


def test_create_local_worktree_sandbox_uses_explicit_root(tmp_path):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    assert isinstance(backend, LocalWorktreeBackend)
    assert backend.root_dir == tmp_path.resolve()
    assert backend.get_work_dir() == "/"


def test_local_worktree_file_tools_are_virtualized(tmp_path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    result = backend.read("/README.md")
    assert result.file_data is not None
    assert result.file_data["content"] == "hello\n"

    escaped = backend.read(str(Path("/etc/passwd")))
    assert escaped.error is not None
    assert "not found" in escaped.error or "outside root directory" in escaped.error


def test_local_worktree_executes_from_root_dir(tmp_path):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    result = backend.execute("pwd")

    assert result.exit_code == 0
    assert result.output.strip() == str(tmp_path.resolve())


@pytest.mark.parametrize(
    "command",
    [
        "cat /etc/passwd",
        "ls /",
        "cd .. && pwd",
        "git push origin HEAD",
        "git reset --hard HEAD",
        "git clean -fd",
        "git switch main",
        "git checkout main",
        "git worktree list",
        "git remote -v",
        "git branch -D old-branch",
        "rm -rf .",
        "rm -fr ./build",
        "sudo ls",
        "echo $HOME",
    ],
)
def test_local_worktree_blocks_dangerous_commands(tmp_path, command):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    result = backend.execute(command)

    assert result.exit_code == 126
    assert "blocked by local worktree policy" in result.output


def test_local_worktree_allows_common_git_revision_syntax(tmp_path):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    result = backend.execute("echo HEAD~1")

    assert result.exit_code == 0
    assert "HEAD~1" in result.output


def test_local_worktree_allows_read_only_git_commands(tmp_path):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    init = backend.execute("git init")
    result = backend.execute("git status --short")

    assert init.exit_code == 0
    assert result.exit_code == 0


def test_local_worktree_allows_git_commit(tmp_path):
    backend = create_local_worktree_sandbox(root_dir=tmp_path)

    result = backend.execute(
        "git init && "
        "git config user.name Test && "
        "git config user.email test@example.com && "
        "printf 'hello\\n' > README.md && "
        "git add README.md && "
        "git commit -m init"
    )

    assert result.exit_code == 0
