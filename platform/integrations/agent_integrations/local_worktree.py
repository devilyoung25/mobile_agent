"""Local worktree sandbox backend.

This is a local-development guardrail, not OS-level isolation. It binds the
agent's filesystem tools to one git worktree and runs shell commands from that
directory with a filtered environment.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

SAFE_ENV_KEYS = {
    "ANDROID_HOME",
    "ANDROID_SDK_ROOT",
    "GRADLE_USER_HOME",
    "HOME",
    "JAVA_HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SHELL",
    "TMPDIR",
    "USER",
}

FORBIDDEN_EXECUTABLES = {
    "az",
    "chmod",
    "chown",
    "diskutil",
    "docker",
    "gh",
    "mkfs",
    "rsync",
    "scp",
    "ssh",
    "su",
    "sudo",
}

FORBIDDEN_SNIPPETS = (
    "$HOME",
    "${HOME}",
    "/.ssh",
    "/.azure",
    "/.config",
    "/.kube",
    "/etc/",
    "/private/etc/",
    "rm -rf /",
    "rm -fr /",
    "rm -rf .",
    "rm -fr .",
)

ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])(/[^\s'\";|&()<>]+)")


def _safe_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS and value}


def _normalize_root_dir(root_dir: str | os.PathLike[str]) -> Path:
    root_path = Path(root_dir).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"local worktree root does not exist: {root_path}")
    return root_path


def _is_inside_root(candidate: str, root_dir: Path) -> bool:
    try:
        Path(candidate).expanduser().resolve().relative_to(root_dir)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _iter_executables(tokens: list[str]):
    control_tokens = {"&&", "||", ";", "|"}
    expect_command = True
    for token in tokens:
        if token in control_tokens:
            expect_command = True
            continue
        if not token or token.startswith("-"):
            continue
        if expect_command:
            yield Path(token).name
            expect_command = False
            continue
        expect_command = False
    return None


_GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--config-env",
    "--git-dir",
    "--namespace",
    "--work-tree",
}
_FORBIDDEN_GIT_SUBCOMMANDS = {
    "checkout",
    "clean",
    "push",
    "remote",
    "reset",
    "switch",
    "worktree",
}


def _git_policy_error(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        if Path(token).name != "git":
            continue

        subcommand_index = index + 1
        while subcommand_index < len(tokens):
            candidate = tokens[subcommand_index]
            if candidate in _GIT_OPTIONS_WITH_VALUE:
                subcommand_index += 2
                continue
            if candidate.startswith("-"):
                subcommand_index += 1
                continue
            break

        if subcommand_index >= len(tokens):
            continue

        subcommand = tokens[subcommand_index]
        if subcommand in _FORBIDDEN_GIT_SUBCOMMANDS:
            return "Command blocked by local worktree policy: dangerous git operation."
        if subcommand == "branch":
            branch_args = tokens[subcommand_index + 1 :]
            if any(arg in {"-d", "-D", "--delete"} for arg in branch_args):
                return "Command blocked by local worktree policy: dangerous git operation."
    return None


def _validate_command(command: str, root_dir: Path) -> str | None:
    stripped = command.strip()
    if not stripped:
        return "Command must be a non-empty string."

    lowered = stripped.lower()
    for snippet in FORBIDDEN_SNIPPETS:
        if snippet.lower() in lowered:
            return f"Command blocked by local worktree policy: forbidden reference '{snippet}'."

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError as exc:
        return f"Command blocked by local worktree policy: cannot parse shell command ({exc})."

    for executable in _iter_executables(tokens):
        if executable in FORBIDDEN_EXECUTABLES:
            return f"Command blocked by local worktree policy: '{executable}' is not allowed."

    git_error = _git_policy_error(tokens)
    if git_error:
        return git_error

    for token in tokens:
        if token == "~" or token.startswith("~/"):
            return "Command blocked by local worktree policy: home-relative paths are not allowed."
        if token == ".." or token.startswith("../") or "/../" in token:
            return "Command blocked by local worktree policy: path traversal is not allowed."
        if token.startswith("/") and token not in {"/dev/null", "/dev/zero"}:
            if not _is_inside_root(token, root_dir):
                return (
                    "Command blocked by local worktree policy: absolute paths outside "
                    "the selected workspace are not allowed."
                )

    for match in ABSOLUTE_PATH_RE.finditer(stripped):
        path = match.group(1)
        if path in {"/dev/null", "/dev/zero"}:
            continue
        if not _is_inside_root(path, root_dir):
            return (
                "Command blocked by local worktree policy: absolute paths outside "
                "the selected workspace are not allowed."
            )

    return None


class LocalWorktreeBackend:
    """SandboxBackendProtocol wrapper bound to one local git worktree."""

    def __init__(
        self,
        root_dir: str | os.PathLike[str],
        *,
        sandbox_id: str | None = None,
        inherit_env: bool = False,
    ) -> None:
        self.root_dir = _normalize_root_dir(root_dir)
        env = None if inherit_env else _safe_env()
        self._backend = LocalShellBackend(
            root_dir=self.root_dir,
            virtual_mode=True,
            env=env,
            inherit_env=inherit_env,
        )
        stable_id = str(self.root_dir).replace("/", "-").strip("-")
        self._sandbox_id = sandbox_id or f"local-worktree-{stable_id[-48:]}"

    @property
    def id(self) -> str:
        return self._sandbox_id

    def get_work_dir(self) -> str:
        return "/"

    def ls(self, path: str) -> LsResult:
        return self._backend.ls(path)

    async def als(self, path: str) -> LsResult:
        return await self._backend.als(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return self._backend.read(file_path, offset, limit)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return await self._backend.aread(file_path, offset, limit)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return self._backend.grep(pattern, path, glob)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return await self._backend.agrep(pattern, path, glob)

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        return self._backend.glob(pattern, path)

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        return await self._backend.aglob(pattern, path)

    def write(self, file_path: str, content: str) -> WriteResult:
        return self._backend.write(file_path, content)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return await self._backend.awrite(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return self._backend.edit(file_path, old_string, new_string, replace_all)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return await self._backend.aedit(file_path, old_string, new_string, replace_all)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self._backend.upload_files(files)

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return await self._backend.aupload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._backend.download_files(paths)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await self._backend.adownload_files(paths)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        error = _validate_command(command, self.root_dir)
        if error:
            return ExecuteResponse(output=error, exit_code=126, truncated=False)
        return self._backend.execute(command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        error = _validate_command(command, self.root_dir)
        if error:
            return ExecuteResponse(output=error, exit_code=126, truncated=False)
        return await self._backend.aexecute(command, timeout=timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


def create_local_worktree_sandbox(
    sandbox_id: str | None = None,
    *,
    root_dir: str | os.PathLike[str] | None = None,
):
    """Create a local worktree backend.

    ``root_dir`` is passed by the dashboard runtime when a thread has a selected
    workspace. The env fallback keeps the provider usable from SANDBOX_TYPE for
    local debugging, but a workspace thread should always pass an explicit root.
    """
    resolved_root = root_dir or os.getenv("LOCAL_WORKTREE_SANDBOX_ROOT_DIR")
    if not resolved_root:
        resolved_root = os.getenv("LOCAL_SANDBOX_ROOT_DIR", os.getcwd())

    inherit_env = os.getenv("LOCAL_WORKTREE_SANDBOX_INHERIT_ENV", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return LocalWorktreeBackend(resolved_root, sandbox_id=sandbox_id, inherit_env=inherit_env)
