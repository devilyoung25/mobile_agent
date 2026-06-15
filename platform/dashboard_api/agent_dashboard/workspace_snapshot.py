"""Read-only snapshot of a prepared workspace worktree.

Computes a safe summary of what the agent changed relative to the persisted base
commit (the worktree's prep HEAD): line stats, changed files, commits and dirty
status. Deliberately small and side-effect free:

- never returns a full patch (avoids token blow-up and secret leakage),
- never surfaces git stderr (it can carry remote URLs / credential hints),
- runs every git command under a strict timeout.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

_STATUS_LABELS = {
    "A": "added",
    "C": "copied",
    "D": "deleted",
    "M": "modified",
    "R": "renamed",
    "T": "type_changed",
    "U": "unmerged",
}


def _git(path: str, *args: str, timeout: int = 10) -> tuple[int, str]:
    """Run a git command, returning ``(returncode, stdout)``. Never raises, never
    propagates stderr."""
    try:
        result = subprocess.run(
            ["git", "-C", path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return 1, ""
    return result.returncode, result.stdout


def _status_label(code: str) -> str:
    return _STATUS_LABELS.get((code or "")[:1].upper(), "modified")


def _parse_count(value: str) -> int | None:
    """numstat counts are digits, or ``-`` for binary files."""
    return int(value) if value.isdigit() else None


def _commits(path: str, base_commit: str, head_commit: str) -> list[dict[str, str]]:
    if not head_commit or head_commit == base_commit:
        return []
    _, log = _git(path, "log", "--format=%H%x00%s", f"{base_commit}..HEAD")
    commits: list[dict[str, str]] = []
    for line in log.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        commits.append({"sha": sha, "subject": subject})
    return commits


class SnapshotError(RuntimeError):
    """Raised when git can't produce a trustworthy snapshot (fail closed)."""


def snapshot_workspace_sync(workspace_path: str, base_commit: str) -> dict[str, Any]:
    rc, head = _git(workspace_path, "rev-parse", "HEAD")
    head_commit = head.strip()
    # Fail closed: a missing HEAD means the worktree is gone/broken — don't return a
    # half-built snapshot that the UI would render with false confidence.
    if rc != 0 or not head_commit:
        raise SnapshotError("workspace_snapshot_failed")

    _, porcelain = _git(workspace_path, "status", "--porcelain=v1")
    porcelain_lines = [line for line in porcelain.splitlines() if line.strip()]
    is_dirty = bool(porcelain_lines)
    untracked = [line[3:] for line in porcelain_lines if line.startswith("?? ")]

    _, numstat = _git(workspace_path, "diff", "--numstat", base_commit)
    _, name_status = _git(workspace_path, "diff", "--name-status", base_commit)

    status_by_path: dict[str, str] = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        # Renames/copies end with the destination path.
        status_by_path[parts[-1]] = _status_label(parts[0])

    changed_files: list[dict[str, Any]] = []
    total_additions = 0
    total_deletions = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions = _parse_count(parts[0])
        deletions = _parse_count(parts[1])
        path = parts[-1]
        total_additions += additions or 0
        total_deletions += deletions or 0
        changed_files.append(
            {
                "path": path,
                "status": status_by_path.get(path, "modified"),
                "additions": additions,
                "deletions": deletions,
            }
        )

    tracked = {entry["path"] for entry in changed_files}
    for path in untracked:
        if path not in tracked:
            changed_files.append(
                {"path": path, "status": "added", "additions": None, "deletions": None}
            )

    return {
        "base_commit": base_commit,
        "head_commit": head_commit,
        "is_dirty": is_dirty,
        "diff_stats": {
            "files": len(changed_files),
            "additions": total_additions,
            "deletions": total_deletions,
        },
        "changed_files": changed_files,
        "commits": _commits(workspace_path, base_commit, head_commit),
    }


async def snapshot_workspace(workspace_path: str, base_commit: str) -> dict[str, Any]:
    return await asyncio.to_thread(snapshot_workspace_sync, workspace_path, base_commit)
