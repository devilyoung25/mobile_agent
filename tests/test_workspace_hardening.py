import re
import subprocess
from pathlib import Path

import pytest
from agent.dashboard.workspaces import (
    WorkspaceCreate,
    _prepare_workspace_run_sync,
    _validate_workspace,
    _worktree_branch,
    _worktree_path,
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


def test_validate_workspace_allows_non_azure_with_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_ALLOW_NONAZURE_WORKSPACE", "1")
    repo = _init_repo(tmp_path / "repo", remote="https://github.com/acme/repo.git")

    workspace = _validate_workspace("actor", WorkspaceCreate(path=str(repo), label="GH"))

    assert workspace["remote_url"] == "https://github.com/acme/repo.git"


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


# ---- Run prep (integration / local_branch modes) ----
# These exercise the real fetch + worktree path against a LOCAL bare repo acting as
# origin, so they run offline. The Azure-host gate is covered by the validation tests
# above, so it is stubbed out here to isolate the base-mode logic.


def _setup_origin_source(tmp_path: Path, *, branch: str = "develop") -> Path:
    """Bare origin with ``branch`` + a source clone checked out on ``branch``."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    source = tmp_path / "repo"
    source.mkdir()
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
    _git(source, "checkout", "-b", branch)
    _git(source, "config", "user.name", "Dev User")
    _git(source, "config", "user.email", "dev@example.com")
    (source / "README.md").write_text("base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "base")
    _git(source, "remote", "add", "origin", str(origin))
    _git(source, "push", "-u", "origin", branch)
    return source


def _workspace(source: Path) -> dict:
    return {"id": "ws-test", "path": str(source), "label": "Try"}


def _stub_azure_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent.dashboard.workspaces._validate_azure_devops_remote", lambda *a, **k: None
    )


def test_prepare_integration_mode_bases_on_origin_develop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    develop_sha = _git(source, "rev-parse", "origin/develop")
    # A dev-only (unpushed) commit on the checked-out branch must NOT leak into an
    # integration worktree, which is built straight from origin/develop.
    (source / "local_only.txt").write_text("x\n", encoding="utf-8")
    _git(source, "add", "local_only.txt")
    _git(source, "commit", "-m", "dev local only")

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-int", base_mode="integration")

    assert prepared["base_mode"] == "integration"
    assert prepared["integration_branch"] == "develop"
    assert prepared["integration_target"] == "develop"
    assert prepared["worktree_base_commit"] == develop_sha
    assert prepared["integration_synced"] is True
    worktree = Path(prepared["worktree_path"])
    assert worktree.is_dir()
    assert worktree.is_relative_to(tmp_path / "wt")
    assert not (worktree / "local_only.txt").exists()
    assert prepared["worktree_branch"].startswith("on-mobile-agent/thread-int-")


def test_prepare_integration_mode_is_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-def")

    assert prepared["base_mode"] == "integration"


def test_prepare_integration_branch_configurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.setenv("ON_MOBILE_AGENT_INTEGRATION_BRANCH", "main")
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path, branch="main")

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-main", base_mode="integration")

    assert prepared["integration_branch"] == "main"
    assert prepared["integration_target"] == "main"


def test_prepare_missing_integration_branch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    # origin has only main; default integration branch (develop) is absent.
    source = _setup_origin_source(tmp_path, branch="main")

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-x", base_mode="integration")

    _assert_http_error(exc, 422, "workspace_integration_branch_missing")


def test_prepare_fetch_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.delenv("ON_MOBILE_AGENT_ALLOW_STALE_INTEGRATION", raising=False)
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    # Break origin so the fetch fails (no network/credentials).
    _git(source, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-off", base_mode="integration")

    _assert_http_error(exc, 502, "workspace_fetch_failed")


def test_prepare_fetch_failure_allowed_with_stale_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.setenv("ON_MOBILE_AGENT_ALLOW_STALE_INTEGRATION", "1")
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    _git(source, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-off", base_mode="integration")

    assert prepared["integration_synced"] is False  # proceeded on cached develop
    assert Path(prepared["worktree_path"]).is_dir()


def test_prepare_local_branch_persists_base_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    _git(source, "checkout", "-b", "feature/x")
    (source / "feature.txt").write_text("f\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feature work")
    source_head = _git(source, "rev-parse", "HEAD")

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-inv", base_mode="local_branch")

    # Every base invariant needed for a safe merge-back must be demonstrable.
    assert prepared["source_branch"] == "feature/x"
    assert prepared["source_commit"] == source_head
    assert prepared["integration_branch"] == "develop"
    assert prepared["integration_commit"]
    assert prepared["integration_synced"] is True
    assert prepared["worktree_base_commit"]


def test_prepare_invalid_base_mode_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-x", base_mode="bogus")

    _assert_http_error(exc, 422, "workspace_base_mode_invalid")


def test_prepare_is_idempotent_for_existing_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)

    first = _prepare_workspace_run_sync(_workspace(source), "thread-123", base_mode="integration")
    second = _prepare_workspace_run_sync(_workspace(source), "thread-123", base_mode="integration")

    assert second["worktree_path"] == first["worktree_path"]
    assert second["worktree_branch"] == first["worktree_branch"]


def test_prepare_blocks_dirty_source_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.delenv("ON_MOBILE_AGENT_ALLOW_DIRTY_WORKSPACE", raising=False)
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    (source / "README.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-123", base_mode="integration")

    _assert_http_error(exc, 409, "workspace_source_dirty")


def test_prepare_allows_dirty_source_with_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.setenv("ON_MOBILE_AGENT_ALLOW_DIRTY_WORKSPACE", "1")
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    (source / "README.md").write_text("dirty\n", encoding="utf-8")

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-123", base_mode="integration")

    assert prepared["source_is_dirty"] is True
    assert Path(prepared["worktree_path"]).is_dir()


def test_prepare_local_branch_merges_develop_and_keeps_dev_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    # Dev work on a feature branch forked from the base develop.
    _git(source, "checkout", "-b", "feature/x")
    (source / "feature.txt").write_text("f\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feature work")
    feature_sha_before = _git(source, "rev-parse", "feature/x")
    # Mainline advances on origin while the dev was on their branch.
    _git(source, "checkout", "develop")
    (source / "mainline.txt").write_text("m\n", encoding="utf-8")
    _git(source, "add", "mainline.txt")
    _git(source, "commit", "-m", "mainline advance")
    _git(source, "push", "origin", "develop")
    _git(source, "checkout", "feature/x")

    prepared = _prepare_workspace_run_sync(_workspace(source), "thread-loc", base_mode="local_branch")

    assert prepared["base_mode"] == "local_branch"
    assert prepared["integration_target"] == "feature/x"
    worktree = Path(prepared["worktree_path"])
    assert (worktree / "feature.txt").exists()  # dev's work preserved
    assert (worktree / "mainline.txt").exists()  # latest develop merged in
    # The dev's real branch is never touched.
    assert _git(source, "rev-parse", "feature/x") == feature_sha_before
    # Snapshot base is the worktree's prep HEAD (the merge commit).
    assert prepared["worktree_base_commit"] == _git(worktree, "rev-parse", "HEAD")


def test_prepare_local_branch_merge_conflict_blocks_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    _git(source, "checkout", "-b", "feature/x")
    (source / "README.md").write_text("feature change\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "feature edit")
    _git(source, "checkout", "develop")
    (source / "README.md").write_text("develop change\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "develop edit")
    _git(source, "push", "origin", "develop")
    _git(source, "checkout", "feature/x")

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-conf", base_mode="local_branch")

    _assert_http_error(exc, 409, "workspace_integration_merge_conflict")
    # The worktree is torn down, not left orphaned.
    assert not _worktree_path("ws-test", "thread-conf").exists()


def test_prepare_local_branch_detached_head_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ON_MOBILE_AGENT_WORKTREE_ROOT", str(tmp_path / "wt"))
    _stub_azure_gate(monkeypatch)
    source = _setup_origin_source(tmp_path)
    head = _git(source, "rev-parse", "HEAD")
    _git(source, "checkout", head)  # detached HEAD

    with pytest.raises(HTTPException) as exc:
        _prepare_workspace_run_sync(_workspace(source), "thread-d", base_mode="local_branch")

    _assert_http_error(exc, 422, "workspace_base_branch_required")
