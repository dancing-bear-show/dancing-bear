"""Job handlers registry for worker daemon.

Each handler is a callable: handler(job_dict) -> (success: bool, result_or_error: dict|str)

Built-in handlers:
- run_cli: run a repo bin command (allowlisted bin/ entries); accepts optional
  ``cwd`` payload key to set working directory (defaults to repo root)
- run_shell: run an allowlisted shell program; supports a ``script`` key to
  avoid quoting issues when embedding Python or multi-line scripts

Allowlisted bin commands: mail-assistant, calendar-assistant, schedule-assistant,
phone, resume, whatsapp, worker.
"""

from __future__ import annotations

import os
import stat
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.pipeline import SafeProcessor
from worker._helpers import get_repo_root

HandlerFn = Callable[[dict[str, object]], tuple[bool, object]]


# ---------------------------------------------------------------------------
# ShellJobProcessor — SafeProcessor wrapper for subprocess execution
# ---------------------------------------------------------------------------


@dataclass
class ShellJobRequest:
    """Request for a subprocess shell invocation."""

    cmd: list[str]
    env_overlay: dict[str, str]
    timeout: int
    cwd: str | None


@dataclass
class ShellJobResult:
    """Result of a subprocess shell invocation."""

    returncode: int
    stdout: str
    stderr: str

    def ok(self) -> bool:
        """Return True when the subprocess exited with code 0."""
        return self.returncode == 0


class ShellJobProcessor(SafeProcessor[ShellJobRequest, ShellJobResult]):
    """SafeProcessor wrapping a subprocess shell invocation.

    Raises on timeout or unexpected OS-level errors; returns a ShellJobResult
    on normal subprocess completion (including non-zero exit codes).
    """

    def _process_safe(self, payload: ShellJobRequest) -> ShellJobResult:
        env = os.environ.copy()
        env.update(payload.env_overlay)
        res = subprocess.run(  # nosec B603 - cmd is validated against allowlist before reaching here
            [str(x) for x in payload.cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=payload.timeout,
            text=True,
            env=env,
            cwd=payload.cwd,
        )
        return ShellJobResult(
            returncode=res.returncode,
            stdout=res.stdout[-2000:],
            stderr=res.stderr[-2000:],
        )


# Allowlisted bin commands for dancing-bear
_ALLOWED_BIN_NAMES = {
    "mail-assistant",
    "calendar-assistant",
    "schedule-assistant",
    "phone",
    "resume",
    "whatsapp",
    "worker",
}


def _is_allowed_bin(cmd: str) -> bool:
    p = Path(cmd)
    if not p.is_absolute():
        # Must be one of the allowlisted names
        name = p.name
        if name not in _ALLOWED_BIN_NAMES:
            return False
        p = (get_repo_root() / "bin" / name).resolve()
    try:
        p = p.resolve()
    except Exception:
        return False
    bin_dir = (get_repo_root() / "bin").resolve()
    return p.is_relative_to(bin_dir) and p.exists() and os.access(str(p), os.X_OK)


def _build_command(prog: str, cmd_list: list) -> list[str]:
    """Build command with absolute path for bin programs."""
    if not Path(prog).is_absolute():
        prog_path = str((get_repo_root() / "bin" / prog).resolve())
        return [prog_path] + [str(x) for x in cmd_list[1:]]
    else:
        return [prog] + [str(x) for x in cmd_list[1:]]


def _execute_subprocess(cmd: list[str], env_overlay: dict, timeout: int, cwd: str | None = None) -> dict:  # pragma: no cover - subprocess execution
    """Execute command as a subprocess via ShellJobProcessor. Returns dict with returncode, stdout, stderr."""
    from core.pipeline import RequestConsumer
    request = ShellJobRequest(
        cmd=[str(x) for x in cmd],
        env_overlay={k: str(v) for k, v in env_overlay.items()},
        timeout=timeout,
        cwd=cwd,
    )
    envelope = ShellJobProcessor().process(RequestConsumer(request).consume())
    if not envelope.ok():
        # SafeProcessor caught a subprocess-level error (e.g. TimeoutExpired, OSError)
        msg = (envelope.diagnostics or {}).get("message", "subprocess error")
        raise RuntimeError(msg)
    result = envelope.unwrap()
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _execute_command(cmd: list[str], env_overlay: dict, timeout: int, cwd: str | None = None) -> dict:  # pragma: no cover - subprocess execution
    """Execute a repo-bin command, defaulting to repo root when cwd is not given."""
    return _execute_subprocess(cmd, env_overlay, timeout, cwd=cwd or str(get_repo_root()))


def _validate_run_cli_payload(
    payload: dict[str, object],
) -> tuple[str, None, None] | tuple[None, str, list]:
    """Validate payload.cmd and its program. Returns (error, None, None) or (None, prog, cmd_list)."""
    cmd_list = list(payload.get("cmd") or [])
    if not cmd_list:
        return "missing payload.cmd", None, None
    prog = str(cmd_list[0])
    if not _is_allowed_bin(prog):
        return f"disallowed or missing program: {prog}", None, None
    return None, prog, cmd_list


def _parse_run_cli_timeout(payload: dict[str, object]) -> int:
    try:
        return int(payload.get("timeout") or 300)
    except Exception:  # nosec B110 - fallback to default timeout
        return 300


def handle_run_cli(job: dict[str, object]) -> tuple[bool, object]:  # pragma: no cover - subprocess execution
    """Run a repo bin command with args.

    payload schema: {"cmd": ["bin_name_or_path", "arg1", ...], "env": {..}, "timeout": 300, "cwd": "/optional/path"}
    """
    payload = dict(job.get("payload") or {})
    error, prog, cmd_list = _validate_run_cli_payload(payload)
    if error:
        return (False, error)

    cmd = _build_command(prog, cmd_list)
    env_overlay = dict(payload.get("env") or {})
    cwd = str(payload.get("cwd") or "").strip() or None
    timeout = _parse_run_cli_timeout(payload)

    try:
        out = _execute_command(cmd, env_overlay, timeout, cwd=cwd)
        ok = (int(out.get("returncode", 1)) == 0)
        return (ok, out if ok else out.get("stderr") or out)
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except Exception as e:
        return (False, str(e))


REGISTRY: dict[str, HandlerFn] = {
    "run_cli": handle_run_cli,
}

# --- Optional: generic shell runner (allowlisted) ---
def _shell_allowlist() -> set[str]:
    env = os.getenv("DANCING_BEAR_WORKER_SHELL_ALLOWLIST", "")
    # Setting DANCING_BEAR_WORKER_SHELL_ALLOWLIST *replaces* (not augments) the default
    # allowlist. Only set this variable in trusted deployment environments.
    if env.strip():
        return {s.strip() for s in env.split(",") if s.strip()}
    # Conservative defaults; extend via env as needed
    return {
        "python3",
        "bash",
        "sh",
        "sed",
        "awk",
        "rg",
        "jq",
        "cat",
        "ls",
        "find",
        "grep",
        "head",
        "tail",
        "wc",
    }


def _get_shell_allowlist() -> set[str]:
    """Get shell allowlist."""
    return _shell_allowlist()


def _execute_shell_command(argv: list[str], env_overlay: dict, timeout: int, cwd: str | None) -> dict:  # pragma: no cover - subprocess execution
    """Execute a shell command."""
    return _execute_subprocess(argv, env_overlay, timeout, cwd=cwd)


def _write_script_tempfile(script: str) -> str:
    """Write script content to a temp file, make it executable, and return its path."""
    fd, path = tempfile.mkstemp(suffix=".sh")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(script)
        os.chmod(path, stat.S_IRWXU)
    except Exception:
        try:
            os.unlink(path)
        except OSError:  # nosec B110 - best-effort cleanup; original error is re-raised below
            pass
        raise
    return path


def _needs_tempfile(script: str) -> bool:
    """Return True when the script contains characters that require temp-file dispatch."""
    return "\n" in script or '"' in script or "'" in script


def _resolve_exec_context(payload: dict[str, object]) -> tuple[dict, int, str | None]:
    """Extract env overlay, timeout, and cwd from a job payload."""
    env_overlay = dict(payload.get("env") or {})
    try:
        timeout = int(payload.get("timeout") or 300)
    except Exception:  # nosec B110 - fallback to default timeout
        timeout = 300
    cwd = str(payload.get("cwd") or "") or None
    if cwd is None:
        cwd = str(get_repo_root())
    return env_overlay, timeout, cwd


def _exec_shell_result(out: dict) -> tuple[bool, object]:
    """Convert a shell command output dict to a (ok, result) tuple."""
    ok = int(out.get("returncode", 1)) == 0
    return (ok, out if ok else out.get("stderr") or out)


def _run_via_tempfile(
    script: str, payload: dict[str, object], extra_args: list[str] | None = None
) -> tuple[bool, object]:  # pragma: no cover - subprocess execution
    """Write script to a temp file and execute it with bash."""
    env_overlay, timeout, cwd = _resolve_exec_context(payload)
    tmp_path = _write_script_tempfile(script)
    cmd = ["bash", tmp_path] + (extra_args or [])
    try:
        out = _execute_shell_command(cmd, env_overlay, timeout, cwd)
        return _exec_shell_result(out)
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except Exception as exc:
        return (False, str(exc))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _dispatch_script_key(
    payload: dict[str, object], raw_script: object
) -> tuple[bool, object]:  # pragma: no cover - subprocess execution
    """Handle the ``script`` payload key path."""
    script = str(raw_script).strip()
    if not script:
        return (False, "payload.script is empty")
    if "bash" not in _get_shell_allowlist():
        return (False, "disallowed program: bash")
    return _run_via_tempfile(script, payload)


def _maybe_promote_to_tempfile(
    prog: str, argv: list, payload: dict[str, object]
) -> tuple[bool, object] | None:  # pragma: no cover - subprocess execution
    """Auto-promote ``bash -c <script>`` to temp-file dispatch when needed."""
    if prog != "bash" or len(argv) < 3 or argv[1] != "-c":
        return None
    script_body = str(argv[2])
    if not _needs_tempfile(script_body):
        return None
    return _run_via_tempfile(script_body, payload, extra_args=[str(a) for a in argv[3:]])


def _dispatch_argv(
    payload: dict[str, object], argv: list
) -> tuple[bool, object]:  # pragma: no cover - subprocess execution
    """Execute an argv-based shell job, with auto-promotion for quote-heavy scripts."""
    prog = str(argv[0])
    if prog not in _get_shell_allowlist():
        return (False, f"disallowed program: {prog}")

    promoted = _maybe_promote_to_tempfile(prog, argv, payload)
    if promoted is not None:
        return promoted

    env_overlay, timeout, cwd = _resolve_exec_context(payload)
    try:
        out = _execute_shell_command(argv, env_overlay, timeout, cwd)
        return _exec_shell_result(out)
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except Exception as e:
        return (False, str(e))


def handle_run_shell(job: dict[str, object]) -> tuple[bool, object]:  # pragma: no cover - subprocess execution
    """Run an arbitrary program with arguments (allowlisted).

    Two payload schemas are supported:

    1. ``argv``-based:
       ``{"argv": ["python3", "-c", "print('hi')"], "env": {..}, "timeout": 300, "cwd": "."}``

    2. ``script``-based (recommended for multi-line or quote-heavy scripts):
       ``{"script": "python3 -c \\"print('hello')\\"\\necho done", "env": {..}, "timeout": 3600}``

    Restricts the program to an allowlist controlled by DANCING_BEAR_WORKER_SHELL_ALLOWLIST.
    """
    payload = dict(job.get("payload") or {})

    # Prefer ``script`` key — write to temp file to avoid quote-escaping issues.
    raw_script = payload.get("script")
    if raw_script is not None:
        return _dispatch_script_key(payload, raw_script)

    # Fall back to ``argv``-based dispatch.
    argv = list(payload.get("argv") or [])
    if not argv:
        return (False, "missing payload.argv and payload.script")

    return _dispatch_argv(payload, argv)


# Export optional handler (registered under a separate key)
REGISTRY["run_shell"] = handle_run_shell


def _dispatch_workflow_stage_script(job: dict[str, object], payload: dict[str, object], script: str, workspace_dir: str | None) -> tuple[bool, object]:
    shell_job = dict(job)
    shell_payload = {**payload, "script": script}
    if workspace_dir:
        shell_payload["cwd"] = workspace_dir
    shell_job["payload"] = shell_payload
    return handle_run_shell(shell_job)


def _dispatch_workflow_stage_cli_commands(
    job: dict[str, object], payload: dict[str, object], cli_commands: list[str], workspace_dir: str | None
) -> tuple[bool, object]:
    import shlex
    results = []
    for raw_cmd in cli_commands:
        cli_job = dict(job)
        cli_payload = {**payload, "cmd": shlex.split(raw_cmd)}
        if workspace_dir:
            cli_payload["cwd"] = workspace_dir
        cli_job["payload"] = cli_payload
        ok, result = handle_run_cli(cli_job)
        results.append(result)
        # Partial results from earlier successful commands are intentionally discarded on
        # first failure — parity with original inline logic; tuple contract returns one result.
        if not ok:
            return (False, result)
    return (True, results)


def handle_workflow_stage(job: dict[str, object]) -> tuple[bool, object]:
    """Execute a workflow stage dispatched by WorkerQueueDispatcher.

    Runs the stage's ``script`` payload key via handle_run_shell, falling back
    to ``cli_commands`` via handle_run_cli when no script is present.

    payload schema::

        {
            "workflow_name": str,
            "stage_name": str,
            "stage_index": int,
            "script": str,          # non-empty for executor=worker_queue stages
            "cli_commands": [...],  # derived from invoke-mode outputs
            "workspace_dir": str,
            "trigger_params": {...},
        }
    """
    payload = dict(job.get("payload") or {})
    workspace_dir = str(payload.get("workspace_dir") or "").strip() or None

    script = str(payload.get("script") or "").strip()
    if script:
        return _dispatch_workflow_stage_script(job, payload, script, workspace_dir)

    cli_commands = list(payload.get("cli_commands") or [])
    if cli_commands:
        return _dispatch_workflow_stage_cli_commands(job, payload, cli_commands, workspace_dir)

    return (False, "workflow_stage job has neither script nor cli_commands")


REGISTRY["workflow_stage"] = handle_workflow_stage
