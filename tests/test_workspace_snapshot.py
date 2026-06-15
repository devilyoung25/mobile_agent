import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from agent.dashboard.thread_api import snapshot_dashboard_workspace
from agent.dashboard.workspace_snapshot import SnapshotError, snapshot_workspace_sync
from fastapi import HTTPException


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


def _git_out(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base")
    return repo


# ---- snapshot_workspace_sync (pure git, no mocks) ----


def test_snapshot_reports_committed_and_uncommitted_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git_out(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "add line")
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "new file")
    # leave an uncommitted edit
    (repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    snap = snapshot_workspace_sync(str(repo), base)

    assert snap["base_commit"] == base
    assert snap["head_commit"] == _git_out(repo, "rev-parse", "HEAD")
    assert snap["is_dirty"] is True
    paths = {entry["path"] for entry in snap["changed_files"]}
    assert {"a.txt", "b.txt"} <= paths
    assert snap["diff_stats"]["files"] >= 2
    assert snap["diff_stats"]["additions"] >= 2
    subjects = {commit["subject"] for commit in snap["commits"]}
    assert {"add line", "new file"} <= subjects


def test_snapshot_lists_untracked_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git_out(repo, "rev-parse", "HEAD")
    (repo / "untracked.txt").write_text("u\n", encoding="utf-8")

    snap = snapshot_workspace_sync(str(repo), base)

    assert snap["is_dirty"] is True
    entry = next(f for f in snap["changed_files"] if f["path"] == "untracked.txt")
    assert entry["status"] == "added"


def test_snapshot_binary_numstat_does_not_crash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git_out(repo, "rev-parse", "HEAD")
    (repo / "img.bin").write_bytes(bytes(range(256)))
    _git(repo, "add", "img.bin")
    _git(repo, "commit", "-m", "bin")

    snap = snapshot_workspace_sync(str(repo), base)

    entry = next(f for f in snap["changed_files"] if f["path"] == "img.bin")
    assert entry["additions"] is None
    assert entry["deletions"] is None


def test_snapshot_fails_closed_on_broken_worktree(tmp_path: Path) -> None:
    # Not a git repo -> `rev-parse HEAD` fails -> raise instead of a half-built snapshot.
    with pytest.raises(SnapshotError):
        snapshot_workspace_sync(str(tmp_path), "deadbeef")


def test_snapshot_clean_worktree_has_no_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git_out(repo, "rev-parse", "HEAD")

    snap = snapshot_workspace_sync(str(repo), base)

    assert snap["is_dirty"] is False
    assert snap["diff_stats"] == {"files": 0, "additions": 0, "deletions": 0}
    assert snap["commits"] == []
    assert snap["head_commit"] == base


# ---- snapshot_dashboard_workspace (service, mocked client) ----


def _owned_thread(**metadata: object) -> dict:
    return {"metadata": {"source": "dashboard", "owner_id": "me", **metadata}}


async def test_service_non_owner_returns_404_and_runs_no_git() -> None:
    thread = {"metadata": {"source": "dashboard", "owner_id": "someone-else"}}
    with (
        patch("agent.dashboard.thread_api.langgraph_client") as client,
        patch(
            "agent.dashboard.thread_api.snapshot_workspace", new_callable=AsyncMock
        ) as snap,
    ):
        client.return_value.threads.get = AsyncMock(return_value=thread)
        with pytest.raises(HTTPException) as exc:
            await snapshot_dashboard_workspace("thread-1", "me", email=None)

    assert exc.value.status_code == 404
    snap.assert_not_awaited()


async def test_service_without_workspace_returns_404() -> None:
    thread = _owned_thread()
    with (
        patch("agent.dashboard.thread_api.langgraph_client") as client,
        patch(
            "agent.dashboard.thread_api.snapshot_workspace", new_callable=AsyncMock
        ) as snap,
    ):
        client.return_value.threads.get = AsyncMock(return_value=thread)
        with pytest.raises(HTTPException) as exc:
            await snapshot_dashboard_workspace("thread-1", "me")

    assert exc.value.status_code == 404
    assert exc.value.detail == "workspace_not_attached"
    snap.assert_not_awaited()


async def test_service_snapshot_failure_returns_502() -> None:
    thread = _owned_thread(
        workspace_worktree_path="/wt",
        workspace_worktree_base_commit="base-sha",
    )
    with (
        patch("agent.dashboard.thread_api.langgraph_client") as client,
        patch(
            "agent.dashboard.thread_api.snapshot_workspace",
            new_callable=AsyncMock,
            side_effect=SnapshotError("boom"),
        ),
    ):
        client.return_value.threads.get = AsyncMock(return_value=thread)
        with pytest.raises(HTTPException) as exc:
            await snapshot_dashboard_workspace("thread-1", "me")

    assert exc.value.status_code == 502
    assert exc.value.detail == "workspace_snapshot_failed"


async def test_service_happy_path_updates_thread_metadata() -> None:
    thread = _owned_thread(
        workspace_worktree_path="/wt",
        workspace_worktree_base_commit="base-sha",
    )
    result = {
        "base_commit": "base-sha",
        "head_commit": "head-sha",
        "is_dirty": True,
        "diff_stats": {"files": 1, "additions": 2, "deletions": 0},
        "changed_files": [{"path": "a.txt"}],
        "commits": [],
    }
    with (
        patch("agent.dashboard.thread_api.langgraph_client") as client,
        patch(
            "agent.dashboard.thread_api.snapshot_workspace",
            new_callable=AsyncMock,
            return_value=result,
        ) as snap,
    ):
        client.return_value.threads.get = AsyncMock(return_value=thread)
        client.return_value.threads.update = AsyncMock()

        out = await snapshot_dashboard_workspace("thread-1", "me")

    assert out is result
    snap.assert_awaited_once_with("/wt", "base-sha")
    update_meta = client.return_value.threads.update.await_args.kwargs["metadata"]
    assert update_meta["diff_stats"] == result["diff_stats"]
    assert update_meta["changed_files"] == result["changed_files"]
    assert update_meta["workspace_head_commit"] == "head-sha"
    assert update_meta["workspace_has_uncommitted_changes"] is True
