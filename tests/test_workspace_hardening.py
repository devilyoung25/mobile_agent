import re
import subprocess
from pathlib import Path

import pytest
from agent.dashboard.workspaces import (
    WorkspaceCreate,
    _prepare_workspace_run_sync,
    _validate_workspace,
    _worktree_branch,
)
from fastapi import HTTPException

ADO_REMOTE = "https://token@dev.azure.com/onoff-solution/AppMovil/_git/TryController"


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path, *, remote: str | None = ADO_REMOTE) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    _git(path, "checkout", "-b", "develop")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    if remote:
        _git(path, "remote", "add", "origin", remote)
    return path


def _assert_http_error(exc: pytest.ExceptionInfo[HTTPException], status: int, detail: str) -> None:
    assert exc.value.status_code == status
    assert exc.value.detail == detail


def test_validate_workspace_rejects_empty_path() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=" "))

    _assert_http_error(exc, 400, "workspace_path_required")


def test_validate_workspace_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(tmp_path / "missing")))

    _assert_http_error(exc, 422, "workspace_path_not_directory")


def test_validate_workspace_rejects_non_git_directory(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(tmp_path)))

    _assert_http_error(exc, 422, "workspace_path_not_git_repo")


def test_validate_workspace_rejects_missing_origin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", remote=None)

    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(repo)))

    _assert_http_error(exc, 422, "workspace_path_missing_origin")


def test_validate_workspace_rejects_non_azure_origin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", remote="https://github.com/acme/repo.git")

    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(repo)))

    _assert_http_error(exc, 422, "workspace_path_not_azure_repo")


def test_validate_workspace_rejects_fake_azure_origin_in_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", remote="https://example.com/dev.azure.com/org/repo")

    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(repo)))

    _assert_http_error(exc, 422, "workspace_path_not_azure_repo")


def test_validate_workspace_rejects_wrong_azure_org(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff-solution")
    repo = _init_repo(
        tmp_path / "repo",
        remote="https://dev.azure.com/other-org/AppMovil/_git/TryController",
    )

    with pytest.raises(HTTPException) as exc:
        _validate_workspace("actor", WorkspaceCreate(path=str(repo)))

    _assert_http_error(exc, 422, "workspace_path_wrong_azure_org")


def test_validate_workspace_accepts_azure_origin_and_sanitizes_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "https://dev.azure.com/onoff-solution/")
    repo = _init_repo(tmp_path / "repo")

    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))

    assert workspace["label"] == "Try"
    assert workspace["path"] == str(repo.resolve())
    assert workspace["current_branch"] == "develop"
    assert workspace["remote_url"] == (
        "https://dev.azure.com/onoff-solution/AppMovil/_git/TryController"
    )
    assert workspace["is_dirty"] is False


def test_validate_workspace_accepts_azure_ssh_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_MCP_ORG", "onoff-solution")
    repo = _init_repo(
        tmp_path / "repo",
        remote="ssh://git@ssh.dev.azure.com/v3/onoff-solution/AppMovil/TryController",
    )

    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))

    assert workspace["remote_url"] == (
        "ssh://ssh.dev.azure.com/v3/onoff-solution/AppMovil/TryController"
    )


def test_worktree_branch_uses_hash_to_avoid_prefix_collisions() -> None:
    first = _worktree_branch("thread-with-the-same-prefix-111111")
    second = _worktree_branch("thread-with-the-same-prefix-222222")

    assert first != second
    assert first.startswith("on-mobile-agent/thread-with-the-same-pre")
    assert re.fullmatch(r"on-mobile-agent/[A-Za-z0-9._-]+-[0-9a-f]{8}", first)


def test_prepare_workspace_run_creates_isolated_worktree_and_preserves_source_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    repo = _init_repo(tmp_path / "repo")
    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))

    prepared = _prepare_workspace_run_sync(workspace, "thread-123")

    assert prepared["source_path"] == str(repo.resolve())
    assert prepared["source_branch"] == "develop"
    assert prepared["source_is_dirty"] is False
    assert prepared["worktree_branch"].startswith("on-mobile-agent/thread-123-")
    assert Path(prepared["worktree_path"]).is_dir()
    assert Path(prepared["worktree_path"]).is_relative_to(tmp_path / "worktrees")
    assert _git(repo, "branch", "--show-current") == "develop"
    assert _git(Path(prepared["worktree_path"]), "branch", "--show-current") == prepared[
        "worktree_branch"
    ]


def test_prepare_workspace_run_is_idempotent_for_existing_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    repo = _init_repo(tmp_path / "repo")
    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))

    first = _prepare_workspace_run_sync(workspace, "thread-123")
    second = _prepare_workspace_run_sync(workspace, "thread-123")

    assert second["worktree_path"] == first["worktree_path"]
    assert second["worktree_branch"] == first["worktree_branch"]


def test_prepare_workspace_run_blocks_dirty_source_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    monkeypatch.delenv("ON_MOBILE_AGENT_ALLOW_DIRTY_WORKSPACE", raising=False)
    repo = _init_repo(tmp_path / "repo")
    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(workspace, "thread-123")

    _assert_http_error(exc, 409, "workspace_source_dirty")


def test_prepare_workspace_run_allows_dirty_source_with_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    monkeypatch.setenv("ON_MOBILE_AGENT_ALLOW_DIRTY_WORKSPACE", "1")
    repo = _init_repo(tmp_path / "repo")
    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="Try"))
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    prepared = _prepare_workspace_run_sync(workspace, "thread-123")

    assert prepared["source_is_dirty"] is True
    assert Path(prepared["worktree_path"]).is_dir()
