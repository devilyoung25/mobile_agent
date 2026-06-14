"""Dev Container worktree sandbox backend.

The agent's *general* controlled execution environment (the model edits code and
runs terminal commands the way other coding agents do, but inside a container for
OS-level isolation over untrusted repo content). File edits happen on the host
worktree, which the Dev Container bind-mounts; shell commands run *inside* the
container via the ``devcontainers/cli`` (``devcontainer exec``).

This is **not** an Android build/test sandbox. Gradle, ADB, the emulator, logcat
and screenshots run on the host through the Mobile QA Runner (controlled, approved
tools) — never here. See ``AGENTS.md`` Architecture Rules.

It composes :class:`LocalWorktreeBackend`: file ops, the ``id``/``get_work_dir``
contract and the command guardrails are inherited; only ``execute``/``aexecute``
are overridden to dispatch through the container.

Path model: file tools are virtualized to the worktree root (``get_work_dir`` ->
"/"), while ``devcontainer exec`` runs in the container's workspace folder (the
mounted worktree). Relative commands therefore line up with the files the agent
sees. The command policy is intentionally lighter than the host worktree's:
inside the container, absolute paths and ``/etc`` are legitimate, so only escape,
remote, and destructive operations are blocked (see ``_validate_container_command``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from deepagents.backends.protocol import ExecuteResponse

from .local_worktree import LocalWorktreeBackend, _iter_executables

logger = logging.getLogger(__name__)

DEFAULT_DEVCONTAINER_CLI = "devcontainer"
_UP_TIMEOUT = 900  # first run may build or pull a base image
_DOWN_TIMEOUT = 120
_DEFAULT_EXEC_TIMEOUT = 600


# Inside a container the container *is* the isolation boundary, so — unlike the
# host `local_worktree` policy — absolute paths, `/etc`, `..` and container-local
# writes are fine. We only block what lets the agent escape the box, touch remote
# infra without approval, or destroy the bind-mounted worktree.
_FORBIDDEN_EXECUTABLES = {"az", "docker", "gh", "rsync", "scp", "ssh", "su", "sudo"}
_FORBIDDEN_GIT = ("git push", "git reset --hard", "git clean ")
_FORBIDDEN_SNIPPETS = ("rm -rf /", "rm -fr /")  # protect the mounted worktree + root


def _validate_container_command(command: str) -> str | None:
    """Lighter, container-appropriate guardrail (see note above)."""
    stripped = command.strip()
    if not stripped:
        return "Command must be a non-empty string."

    lowered = stripped.lower()
    for snippet in _FORBIDDEN_SNIPPETS:
        if snippet in lowered:
            return f"Command blocked by devcontainer policy: forbidden reference '{snippet}'."

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError as exc:
        return f"Command blocked by devcontainer policy: cannot parse shell command ({exc})."

    for executable in _iter_executables(tokens):
        if executable in _FORBIDDEN_EXECUTABLES:
            return f"Command blocked by devcontainer policy: '{executable}' is not allowed."

    joined = " ".join(tokens)
    for pattern in _FORBIDDEN_GIT:
        if pattern in joined:
            return "Command blocked by devcontainer policy: dangerous git operation."

    return None


def _resolve_cli() -> str:
    return os.getenv("DEVCONTAINER_CLI", DEFAULT_DEVCONTAINER_CLI)


def _keep_running() -> bool:
    return os.getenv("DEVCONTAINER_KEEP_RUNNING", "true").lower() in {"1", "true", "yes"}


def validate_devcontainer_startup_config() -> None:
    """Fail fast at server boot if Docker + the devcontainer CLI aren't usable."""
    cli = _resolve_cli()
    if shutil.which(cli) is None:
        raise ValueError(
            f"SANDBOX_TYPE=devcontainer_worktree requires the '{cli}' CLI on PATH "
            "(install with: npm install -g @devcontainers/cli)."
        )
    if shutil.which("docker") is None:
        raise ValueError(
            "SANDBOX_TYPE=devcontainer_worktree requires Docker installed (the "
            "'docker' CLI was not found on PATH)."
        )
    try:
        proc = subprocess.run(  # noqa: S603,S607
            ["docker", "info"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "SANDBOX_TYPE=devcontainer_worktree requires the Docker daemon to be "
            "running (could not run `docker info`). Start Docker Desktop and retry."
        ) from exc
    if proc.returncode != 0:
        raise ValueError(
            "SANDBOX_TYPE=devcontainer_worktree requires the Docker daemon to be "
            "running (`docker info` failed). Start Docker Desktop and retry."
        )


def _build_up_args(cli: str, root_dir: Path) -> list[str]:
    return [cli, "up", "--workspace-folder", str(root_dir)]


def _build_exec_args(cli: str, root_dir: Path, command: str) -> list[str]:
    return [cli, "exec", "--workspace-folder", str(root_dir), "bash", "-lc", command]


def _build_down_args(cli: str, root_dir: Path) -> list[str]:
    return [cli, "down", "--workspace-folder", str(root_dir)]


def _run_capture(argv: list[str], timeout: int | None) -> tuple[int, str]:
    """Run a devcontainer CLI command, returning (exit_code, combined output)."""
    try:
        proc = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, f"devcontainer command timed out after {timeout}s"
    except OSError as exc:
        return 126, f"failed to run devcontainer CLI: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


async def _arun_capture(argv: list[str], timeout: int | None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return 126, f"failed to run devcontainer CLI: {exc}"
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"devcontainer command timed out after {timeout}s"
    return proc.returncode or 0, (stdout or b"").decode(errors="replace")


def _parse_container_id(stdout: str) -> str | None:
    """``devcontainer up`` emits a JSON result line; pull ``containerId`` out of it."""
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            data = json.loads(stripped)
        except ValueError:
            continue
        cid = data.get("containerId")
        if isinstance(cid, str) and cid:
            return cid
    return None


class DevcontainerWorktreeBackend(LocalWorktreeBackend):
    """Worktree backend whose shell runs inside a Dev Container."""

    def __init__(
        self,
        root_dir: str | os.PathLike[str],
        *,
        sandbox_id: str | None = None,
        cli: str | None = None,
        up: bool = True,
    ) -> None:
        super().__init__(root_dir, sandbox_id=sandbox_id, inherit_env=False)
        self._cli = cli or _resolve_cli()
        self._container_id: str | None = None
        stable_id = str(self.root_dir).replace("/", "-").strip("-")
        self._sandbox_id = sandbox_id or f"devcontainer-worktree-{stable_id[-44:]}"
        if up:
            self._bring_up()

    @property
    def container_id(self) -> str | None:
        return self._container_id

    def _bring_up(self) -> None:
        code, out = _run_capture(_build_up_args(self._cli, self.root_dir), _UP_TIMEOUT)
        if code != 0:
            raise RuntimeError(
                f"`devcontainer up` failed (exit {code}) for {self.root_dir}: "
                f"{out.strip()[:2000]}"
            )
        self._container_id = _parse_container_id(out)
        logger.info(
            "devcontainer up for %s -> container %s", self.root_dir, self._container_id
        )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        error = _validate_container_command(command)
        if error:
            return ExecuteResponse(output=error, exit_code=126, truncated=False)
        code, out = _run_capture(
            _build_exec_args(self._cli, self.root_dir, command),
            timeout or _DEFAULT_EXEC_TIMEOUT,
        )
        return ExecuteResponse(output=out, exit_code=code, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        error = _validate_container_command(command)
        if error:
            return ExecuteResponse(output=error, exit_code=126, truncated=False)
        code, out = await _arun_capture(
            _build_exec_args(self._cli, self.root_dir, command),
            timeout or _DEFAULT_EXEC_TIMEOUT,
        )
        return ExecuteResponse(output=out, exit_code=code, truncated=False)

    def down(self) -> None:
        """Stop the dev container unless DEVCONTAINER_KEEP_RUNNING keeps it warm."""
        if _keep_running():
            return
        _run_capture(_build_down_args(self._cli, self.root_dir), _DOWN_TIMEOUT)


def create_devcontainer_worktree_sandbox(
    sandbox_id: str | None = None,
    *,
    root_dir: str | os.PathLike[str] | None = None,
):
    """Create a Dev Container backend bound to a per-thread worktree.

    ``root_dir`` is passed by the dashboard runtime when a thread has a selected
    workspace. The env fallback keeps the provider usable from SANDBOX_TYPE for
    local debugging.
    """
    resolved_root = root_dir or os.getenv("LOCAL_WORKTREE_SANDBOX_ROOT_DIR")
    if not resolved_root:
        resolved_root = os.getenv("LOCAL_SANDBOX_ROOT_DIR", os.getcwd())
    return DevcontainerWorktreeBackend(resolved_root, sandbox_id=sandbox_id)
