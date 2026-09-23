"""qwen_patch job handler: local Ollama-backed code-patch generation.

Registered as ``REGISTRY["qwen_patch"] = handle_qwen_patch`` in
``worker.handlers``. Given a set of repo-relative files and a natural-language
instruction, prompts a local Ollama model (default ``qwen2.5-coder:14b``) to
produce a unified diff, validates the diff with ``git apply --check``, and
writes it to a patch file under ``core.paths.output_dir("qwen")``. The patch
is never applied by this handler.

Guard order (contract.json): input confinement runs FIRST (before any file is
opened and before the concurrency lock), then the memory precheck, then the
lock/model call, then patch validation/caps/disk precheck. See
``handle_qwen_patch`` for the full sequence.

Every string derived from payload content or model output that reaches the
result or telemetry is masked via ``core.secrets.mask_text`` first. The
prompt itself is never persisted; the only place file contents reach disk is
inside the generated patch artifact, which lives outside the checkout.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from core.secrets import mask_text
from worker._helpers import get_repo_root, get_worker_state_dir

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QwenThresholds:
    """Frozen threshold table for the qwen_patch handler's guards."""

    wait_ceiling_sec: float = 180
    lock_poll_interval_sec: float = 2
    stale_ceiling_sec: float = 1200
    deferral_ceiling_count: int = 20
    deferral_wallclock_ceiling_min: float = 45
    model_resident_gb: float = 9
    memory_margin_gb: float = 4
    max_file_bytes: int = 200_000
    max_files: int = 8
    max_lines: int = 400
    min_free_disk_gb: float = 5
    max_lane_depth: int = 10
    ollama_request_timeout_sec: float = 600
    num_ctx: int = 8192


THRESHOLDS = QwenThresholds()

JOB_TYPE = "qwen_patch"
DEFAULT_MODEL_TAG = "qwen2.5-coder:14b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

ALLOWLIST_DIRS = ("src/", "tests/", "bin/", "workflows/", "concerns/", "docs/")
DENYLIST_NAMES = ("credentials.ini", "id_rsa", "id_ed25519")
DENYLIST_SUFFIXES = (".pem", ".p12")
DENIED_PATCH_PREFIXES = (".github/", "bin/", "configs/", ".claude/")


class QwenGuardError(Exception):
    """Raised by a guard that rejects a job; str(exc) is the outcome string."""


def _repo_root() -> Path:
    return get_repo_root()


def _is_denied_name(path: Path) -> bool:
    name = path.name
    if name in DENYLIST_NAMES:
        return True
    if any(name.endswith(suf) for suf in DENYLIST_SUFFIXES):
        return True
    if "token" in name.lower() and name.lower().endswith(".json"):
        return True
    if name.startswith(".env"):
        return True
    return False


def _is_within_allowlist(resolved: Path, root: Path) -> bool:
    for allowed in ALLOWLIST_DIRS:
        candidate = (root / allowed).resolve()
        if resolved.is_relative_to(candidate):
            return True
    return False


def resolve_input_files(files: list[str], repo_root: Path) -> list[Path]:
    """Validate and resolve payload.files against the allowlist/denylist.

    Runs BEFORE any file is opened: resolves the real path (following
    symlinks) and checks containment against the allowlisted directories, and
    rejects denylisted names/suffixes and any path with a .git/ segment.
    Raises QwenGuardError("terminal-path-not-allowed: <path>") on the first
    violation, before touching any later path in the list.
    """
    root = repo_root.resolve()
    resolved: list[Path] = []
    for raw in files:
        candidate = Path(raw)
        p = candidate if candidate.is_absolute() else root / candidate
        try:
            real = p.resolve()
        except OSError as exc:
            raise QwenGuardError(f"terminal-path-not-allowed: {raw}") from exc
        if ".git" in real.parts:
            raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
        if _is_denied_name(real):
            raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
        if not _is_within_allowlist(real, root):
            raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
        resolved.append(real)
    return resolved


def _validate_payload(payload: dict[str, object]) -> tuple[list[str], str]:
    """Validate required payload fields. Raises QwenGuardError on failure."""
    files = payload.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        raise QwenGuardError("terminal-invalid-payload: files must be a non-empty list[str]")
    instruction = payload.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise QwenGuardError("terminal-invalid-payload: instruction must be a non-empty str")
    return files, instruction


# ---------------------------------------------------------------------------
# Module-level seams — each is the ONLY place its side effect happens.
# Tests patch these with mock.patch("worker.qwen.<name>").
# ---------------------------------------------------------------------------


def _ollama_request(url: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    """POST body as JSON to url and parse the JSON response. The only urlopen call site."""
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - url is assembled from ollama_host param, not user input
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed local ollama endpoint, not user-controlled
            raw = resp.read().decode("utf-8")
            return dict(json.loads(raw))
    except urllib.error.HTTPError as exc:
        raise QwenGuardError(f"http-error-{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


def _ollama_tags(host: str, timeout: float) -> dict[str, object]:
    """GET {host}/api/tags and parse the JSON response. Separate from _ollama_request

    because that seam is POST-only (matches interface.md's generate transport
    signature); /api/tags is a GET with no body. Kept as its own tiny seam so
    tests can patch it independently of the generate call.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"{host}/api/tags", method="GET")  # noqa: S310 - fixed local ollama endpoint
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed local ollama endpoint, not user-controlled
            raw = resp.read().decode("utf-8")
            return dict(json.loads(raw))
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


def _model_digest(host: str, model: str) -> str | None:
    """Return the running model's digest via GET {host}/api/tags, or None if unreadable.

    Ollama's POST /api/show does not carry a digest field (its keys are
    license, modelfile, template, system, details, model_info, capabilities,
    modified_at — confirmed against a live install). The digest lives on the
    matching entry in GET /api/tags's models[] list, keyed by "name" ==
    model_tag, under "digest" (full sha256). This deviates from
    interface.md's original description of this seam, which named /api/show;
    recorded as a deviation in handler-impl.json.
    """
    try:
        result = _ollama_tags(host, timeout=10)
    except Exception:  # nosec B110 - digest is informational only; a lookup failure must not fail the job
        return None
    models = result.get("models")
    if not isinstance(models, list):
        return None
    for entry in models:
        if isinstance(entry, dict) and entry.get("name") == model:
            digest = entry.get("digest")
            return str(digest) if isinstance(digest, str) else None
    return None


def _available_memory_bytes() -> int | None:
    """Return free+inactive+speculative memory via macOS vm_stat, or None if unreadable."""
    import subprocess  # nosec B404 - subprocess imported deliberately for vm_stat; call site below carries its own review

    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell, no user input
            ["vm_stat"], capture_output=True, text=True, timeout=5
        )
    except Exception:  # nosec B110 - unavailable_fallback: log and proceed rather than guess
        return None
    if out.returncode != 0:
        return None
    return _parse_vm_stat(out.stdout)


def _parse_vm_stat(text: str) -> int | None:
    """Parse vm_stat output into free+inactive+speculative bytes."""
    page_match = re.search(r"page size of (\d+) bytes", text)
    if not page_match:
        return None
    page_size = int(page_match.group(1))
    wanted = ("Pages free", "Pages inactive", "Pages speculative")
    total_pages = 0
    for line in text.splitlines():
        for label in wanted:
            if line.startswith(label):
                digits = re.sub(r"[^\d]", "", line.split(":", 1)[-1])
                if digits:
                    total_pages += int(digits)
    return total_pages * page_size if total_pages else None


def _free_disk_bytes(path: Path) -> int | None:
    """Return free bytes on the filesystem holding path, or None if unstat-able."""
    import shutil

    try:
        target = path if path.exists() else path.parent
        return shutil.disk_usage(str(target)).free
    except OSError:
        return None


def _lane_depth(job_type: str) -> int:
    """Count pending+processing jobs of job_type (this type only)."""
    from worker import queue_ops

    pending = queue_ops.list_pending(root=queue_ops.QUEUE_ROOT)
    processing = queue_ops.list_processing(root=queue_ops.QUEUE_ROOT)
    count = 0
    for _path, data in [*pending, *processing]:
        if str(data.get("type")) == job_type:
            count += 1
    return count


def _ensure_trailing_newline(text: str) -> str:
    """A unified diff file must end with a newline; git apply reports 'corrupt patch'
    on the final hunk line otherwise, even when the content itself is well-formed."""
    return text if text.endswith("\n") else text + "\n"


def _git_apply_check(patch_text: str, repo_root: Path) -> bool:
    """Validate patch_text with git apply --check against repo_root. True = applies cleanly."""
    import subprocess  # nosec B404 - subprocess imported deliberately for git apply; call site below carries its own review
    import tempfile

    fd, tmp_path = tempfile.mkstemp(suffix=".patch")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(_ensure_trailing_newline(patch_text))
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell; patch content flows through a temp file, not the command line
            ["git", "apply", "--check", tmp_path],
            cwd=str(repo_root),
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:  # nosec B110 - best-effort temp file cleanup
            pass


def _lock_path() -> Path:
    return get_worker_state_dir("qwen") / "model.lock"


def _deferral_dir() -> Path:
    return get_worker_state_dir("qwen") / "deferrals"


def _patch_dir() -> Path:
    from core.paths import output_dir

    return output_dir("qwen") / "patches"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_is_worker(pid: int) -> bool:
    """True when pid's command line names a worker process."""
    import subprocess  # nosec B404 - subprocess imported deliberately for ps; call site below carries its own review

    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv with an int pid, no shell
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
        )
    except Exception:  # nosec B110 - unreadable process table treated as "not a worker"
        return False
    return result.returncode == 0 and "worker" in result.stdout


# ---------------------------------------------------------------------------
# Pure helpers — directly testable without mocks.
# ---------------------------------------------------------------------------

_DIFF_START_RE = re.compile(r"^(?:diff --git|--- )", re.MULTILINE)


def _strip_blank_edge_lines(text: str) -> str:
    """Drop fully-empty leading/trailing lines without touching interior content.

    Unlike str.strip(), this never removes trailing whitespace WITHIN the
    last remaining line — a line holding a single space is a meaningful
    unified-diff context line (an unchanged blank line in the source file),
    not incidental formatting, and stripping it would silently drop that
    hunk line from the patch.
    """
    lines = text.split("\n")
    start = 0
    while start < len(lines) and lines[start] == "":
        start += 1
    end = len(lines)
    while end > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[start:end])


def extract_diff(response_text: str) -> str | None:
    """Extract a unified diff from a model response.

    Tries a fenced ```diff/```patch block first, then falls back to finding
    a bare diff starting at "diff --git" or "--- " with no fence. Returns
    None when neither heuristic finds a diff. The fenced match requires no
    blank line immediately before the closing fence, so a diff whose last
    hunk line is a single-space context line (unchanged blank source line)
    is captured whole rather than truncated.
    """
    fence_match = re.search(r"```(?:diff|patch)?\n(.*?)```", response_text, re.DOTALL)
    if fence_match:
        candidate = _strip_blank_edge_lines(fence_match.group(1).rstrip("\n"))
        if candidate:
            return candidate
    start_match = _DIFF_START_RE.search(response_text)
    if start_match:
        return _strip_blank_edge_lines(response_text[start_match.start():])
    return None


def _parse_diff_header_target(line: str) -> str | None:
    """Parse a +++/--- header line into a bare target path, or None for /dev/null."""
    target = line[4:].strip()
    if target == "/dev/null":
        return None
    if target.startswith(("a/", "b/")):
        target = target[2:]
    return target or None


def diff_stats(patch_text: str) -> tuple[list[str], int]:
    """Return (target paths, added+removed line count) parsed from a unified diff."""
    paths: list[str] = []
    lines_changed = 0
    for line in patch_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            target = _parse_diff_header_target(line)
            if target and target not in paths:
                paths.append(target)
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            lines_changed += 1
    return paths, lines_changed


def check_patch_caps(patch_text: str) -> str | None:
    """Check patch_text against max_files/max_lines/denied prefixes.

    Returns None when the patch is within caps, else the exact terminal
    outcome string. git apply --check happily validates a patch that
    rewrites a denied path, so this is parsed independently.
    """
    paths, lines_changed = diff_stats(patch_text)
    if len(paths) > THRESHOLDS.max_files or lines_changed > THRESHOLDS.max_lines:
        return "terminal-patch-too-broad"
    for target in paths:
        if any(target.startswith(prefix) for prefix in DENIED_PATCH_PREFIXES):
            return "terminal-patch-too-broad"
        if Path(target).is_absolute():
            return "terminal-patch-too-broad"
        if ".." in Path(target).parts:
            return "terminal-patch-too-broad"
    return None


# ---------------------------------------------------------------------------
# Memory / disk / admission guards — each fails OPEN on an unreadable source.
# ---------------------------------------------------------------------------


def _check_memory_guard() -> str | None:
    """Return "deferred-low-memory" if insufficient, else None. Fails open."""
    available = _available_memory_bytes()
    if available is None:
        _log.warning("qwen: memory reading unavailable; proceeding without a memory guard")
        return None
    required_bytes = (THRESHOLDS.model_resident_gb + THRESHOLDS.memory_margin_gb) * (1024**3)
    if available < required_bytes:
        return "deferred-low-memory"
    return None


def _check_disk_guard() -> str | None:
    """Return "deferred-low-disk" if insufficient, else None. Fails open."""
    free = _free_disk_bytes(_patch_dir())
    if free is None:
        _log.warning("qwen: disk reading unavailable; proceeding without a disk guard")
        return None
    if free < THRESHOLDS.min_free_disk_gb * (1024**3):
        return "deferred-low-disk"
    return None


def _check_admission_cap() -> str | None:
    """Return "terminal-lane-over-capacity" if the qwen_patch lane is full, else None."""
    if _lane_depth(JOB_TYPE) >= THRESHOLDS.max_lane_depth:
        return "terminal-lane-over-capacity"
    return None


# ---------------------------------------------------------------------------
# Concurrency lock — O_EXCL acquire, held around the model call only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LockHolder:
    pid: int
    started_at: float


def _read_lock_holder(lock_path: Path) -> _LockHolder | None:
    try:
        raw = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return _LockHolder(pid=int(raw["pid"]), started_at=float(raw["started_at"]))
    except (KeyError, TypeError, ValueError):
        return None


def _lock_verdict(holder: _LockHolder, now: float) -> str:
    """Return "absent"|"active"|"SUSPECT"|"STALE" for an existing lock holder."""
    if not _pid_alive(holder.pid):
        return "STALE"
    age = now - holder.started_at
    if age <= THRESHOLDS.stale_ceiling_sec:
        return "active"
    return "SUSPECT"


def _try_acquire_lock(lock_path: Path) -> bool:
    """Attempt an atomic O_EXCL create of lock_path holding {pid, started_at}."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "started_at": time.time()}).encode("utf-8")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def _reclaim_lock(lock_path: Path) -> bool:
    """Remove a STALE/reclaimable lock and re-attempt acquisition."""
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return _try_acquire_lock(lock_path)


def _handle_existing_lock(lock_path: Path) -> bool:
    """Inspect an existing lock; reclaim if STALE or reclaimable SUSPECT. Returns True if acquired."""
    holder = _read_lock_holder(lock_path)
    if holder is None:
        # Unreadable/corrupt lock file: treat as stale and reclaim.
        return _reclaim_lock(lock_path)
    verdict = _lock_verdict(holder, time.time())
    if verdict == "STALE":
        return _reclaim_lock(lock_path)
    if verdict == "SUSPECT":
        reclaimable = (not _pid_is_worker(holder.pid)) or _lane_depth(JOB_TYPE) == 0
        if reclaimable:
            return _reclaim_lock(lock_path)
    return False


def _acquire_lock_with_wait(lock_path: Path) -> bool:
    """Poll for the lock up to wait_ceiling_sec. Returns True on acquisition."""
    deadline = time.time() + THRESHOLDS.wait_ceiling_sec
    if _try_acquire_lock(lock_path):
        return True
    while time.time() < deadline:
        if _handle_existing_lock(lock_path):
            return True
        time.sleep(THRESHOLDS.lock_poll_interval_sec)
    return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:  # nosec B110 - already released or never acquired; nothing to clean up
        pass


# ---------------------------------------------------------------------------
# Deferral bound — a side-channel file, since q.retry() reloads the job from
# disk and never persists an in-memory payload mutation.
# ---------------------------------------------------------------------------


def _deferral_path(job_id: str) -> Path:
    return _deferral_dir() / f"{job_id}.json"


def _load_deferral_state(job_id: str) -> dict[str, object]:
    path = _deferral_path(job_id)
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return {}


def _record_deferral(job_id: str, reason: str) -> str | None:
    """Record one deferral under reason; returns "terminal-deferral-limit" if the bound is hit."""
    state = _load_deferral_state(job_id)
    count = int(state.get("count", 0)) + 1
    reasons = dict(state.get("reasons") or {})
    reasons[reason] = int(reasons.get(reason, 0)) + 1
    first_deferred_at = float(state.get("first_deferred_at") or time.time())
    new_state = {"count": count, "reasons": reasons, "first_deferred_at": first_deferred_at}
    path = _deferral_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new_state))

    wallclock_min = (time.time() - first_deferred_at) / 60
    if count >= THRESHOLDS.deferral_ceiling_count or wallclock_min >= THRESHOLDS.deferral_wallclock_ceiling_min:
        return "terminal-deferral-limit"
    return None


def _clear_deferral_state(job_id: str) -> None:
    """Delete the deferral side-channel file on any terminal exit for this job id."""
    try:
        _deferral_path(job_id).unlink()
    except FileNotFoundError:  # nosec B110 - nothing to clear, e.g. a job that never deferred
        pass


# ---------------------------------------------------------------------------
# Model pinning and explain mode.
# ---------------------------------------------------------------------------


def _check_model_pin(host: str, model: str, recorded_digest: str | None) -> tuple[str | None, bool | None]:
    """Return (running_digest, digest_matches_recorded). Never fails the job on mismatch."""
    running_digest = _model_digest(host, model)
    if recorded_digest is None or running_digest is None:
        return running_digest, None
    return running_digest, running_digest == recorded_digest


def _explain_report(
    files: list[Path], instruction: str, model: str, options: dict[str, object]
) -> dict[str, object]:
    """Build the explain_mode report: guard results without calling the model."""
    total_bytes = 0
    per_file_bytes: dict[str, int] = {}
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        per_file_bytes[str(f)] = size
        total_bytes += size
    prompt_chars = len(instruction) + total_bytes
    memory_verdict = _check_memory_guard()
    disk_verdict = _check_disk_guard()
    admission_verdict = _check_admission_cap()
    return {
        "resolved_files": [str(f) for f in files],
        "per_file_bytes": per_file_bytes,
        "total_prompt_chars": prompt_chars,
        "estimated_prompt_tokens": prompt_chars // 4,
        "model": model,
        "options": options,
        "guard_results": {
            "confinement": "pass",
            "memory": "pass" if memory_verdict is None else memory_verdict,
            "disk": "pass" if disk_verdict is None else disk_verdict,
            "admission": "pass" if admission_verdict is None else admission_verdict,
        },
    }


# ---------------------------------------------------------------------------
# Prompt assembly and result building.
# ---------------------------------------------------------------------------


def _read_confined_files(files: list[Path]) -> dict[str, str]:
    """Read each resolved, already-confined file. Raises QwenGuardError over max_file_bytes."""
    contents: dict[str, str] = {}
    for f in files:
        try:
            size = f.stat().st_size
        except OSError as exc:
            raise QwenGuardError(f"terminal-path-not-allowed: {f}") from exc
        if size > THRESHOLDS.max_file_bytes:
            raise QwenGuardError(f"terminal-prompt-too-large: {f} exceeds max_file_bytes")
        contents[str(f)] = f.read_text(errors="replace")
    return contents


def _build_prompt(instruction: str, file_contents: dict[str, str]) -> str:
    parts = [f"Instruction: {instruction}", "", "Files:"]
    for path, content in file_contents.items():
        parts.append(f"--- {path} ---")
        parts.append(content)
    parts.append("")
    parts.append("Respond with a single unified diff in a ```diff fenced block.")
    return "\n".join(parts)


def _build_result(
    *,
    patch_path: Path,
    patch_valid: bool,
    files_touched: int,
    lines_changed: int,
    model: str,
    model_digest: str | None,
    digest_matches: bool | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    duration_ms: int,
    deferral_reasons: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "patch_path": str(patch_path),
        "patch_valid": patch_valid,
        "files_touched": files_touched,
        "lines_changed": lines_changed,
        "model": model,
        "model_digest": model_digest,
        "digest_matches_recorded": digest_matches,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "duration_ms": duration_ms,
        "deferral_reasons": deferral_reasons,
    }


class QwenTransientError(Exception):
    """A retryable transport failure (connection refused, timeout, HTTP 5xx).

    Deliberately distinct from QwenGuardError: str(exc) here is NOT an outcome
    string. It becomes a plain (unprefixed) failure per contract.retry_map, so
    job_runtime's normal attempts/backoff loop handles it rather than the
    terminal/deferred fast paths.
    """


def _call_ollama_generate(host: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    """Call /api/generate and classify the failure per contract.retry_map.

    QwenGuardError("http-error-404") -> terminal-model-not-found (a missing
    model stays missing on retry). Any other http-error-* (5xx) and any
    connection-level failure (refused, timeout) are transient and re-raised
    as QwenTransientError so the caller reports a plain, retryable failure.
    """
    try:
        return _ollama_request(host, body, timeout)
    except QwenGuardError as exc:
        if str(exc) == "http-error-404":
            raise QwenGuardError("terminal-model-not-found") from exc
        # Any other HTTP status (5xx) is a server-side transient condition.
        raise QwenTransientError(str(exc)) from exc
    except OSError as exc:
        # ConnectionError and TimeoutError are both OSError subclasses.
        raise QwenTransientError(str(exc)) from exc


def _generate_and_validate_patch(
    *, host: str, model: str, prompt: str, system: str | None, temperature: float,
    max_tokens: int, timeout: float,
) -> tuple[str, dict[str, object]]:
    """Call the model, extract the diff, and validate it.

    Raises QwenGuardError (a terminal/deferred outcome string) or
    QwenTransientError (a plain, retryable failure) on failure.
    """
    body: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": THRESHOLDS.num_ctx},
    }
    if system:
        body["system"] = system
    response = _call_ollama_generate(f"{host}/api/generate", body, timeout)

    response_text = str(response.get("response") or "")
    diff = extract_diff(response_text)
    if diff is None:
        raise QwenGuardError("terminal-no-diff-found")

    repo_root = _repo_root()
    if not _git_apply_check(diff, repo_root):
        raise QwenGuardError("terminal-patch-does-not-apply")

    caps_verdict = check_patch_caps(diff)
    if caps_verdict is not None:
        raise QwenGuardError(caps_verdict)

    return diff, response


def _write_patch_file(job_id: str, diff: str) -> Path:
    patch_dir = _patch_dir()
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_path = patch_dir / f"{job_id}.patch"
    patch_path.write_text(_ensure_trailing_newline(diff))
    return patch_path


def _resolve_payload_options(payload: dict[str, object]) -> dict[str, object]:
    return {
        "model": str(payload.get("model") or DEFAULT_MODEL_TAG),
        "system": payload.get("system") if isinstance(payload.get("system"), str) else None,
        "temperature": float(payload.get("temperature") if isinstance(payload.get("temperature"), (int, float)) else 0.2),
        "max_tokens": int(payload.get("max_tokens") if isinstance(payload.get("max_tokens"), int) else 4096),
        "explain": bool(payload.get("explain") or False),
    }


def _resolve_timeout(payload: dict[str, object]) -> float:
    """payload["timeout"] is only injected by job_runtime for a positive resolved timeout_sec."""
    raw = payload.get("timeout")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return THRESHOLDS.ollama_request_timeout_sec


def _run_with_lock(
    host: str, model: str, prompt: str, options: dict[str, object], timeout: float
) -> tuple[str, dict[str, object]] | str:
    """Acquire the lock, run the model call, release in finally.

    Returns (diff, response) on success, or a string outcome: a
    "terminal-"/"deferred-" prefixed string from QwenGuardError, or a PLAIN
    (unprefixed) string from QwenTransientError — connection-refused,
    timeout, and HTTP 5xx are contract.retry_map "plain" outcomes, so
    job_runtime's ordinary attempts/backoff loop must see them, not the
    terminal/deferred fast paths.
    """
    lock_path = _lock_path()
    if not _acquire_lock_with_wait(lock_path):
        return "deferred-qwen-busy"
    try:
        return _generate_and_validate_patch(
            host=host,
            model=model,
            prompt=prompt,
            system=options["system"],
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            timeout=timeout,
        )
    except QwenGuardError as exc:
        return str(exc)
    except QwenTransientError as exc:
        return str(exc)
    finally:
        _release_lock(lock_path)


def _emit_telemetry(job_id: str, model: str, outcome: str, attempt: int, patch_valid: bool | None,
                     start_ns: int, end_ns: int, prompt_tokens: int | None, completion_tokens: int | None) -> None:
    from worker.qwen_telemetry import export_job_span

    attrs: dict[str, object] = {
        "qwen.job_id": job_id,
        "qwen.job_type": JOB_TYPE,
        "qwen.model": model,
        "qwen.outcome": outcome,
        "qwen.attempt": attempt,
        "qwen.patch_valid": patch_valid,
    }
    if prompt_tokens is not None:
        attrs["qwen.prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        attrs["qwen.completion_tokens"] = completion_tokens
    attrs["qwen.generation_duration_ms"] = (end_ns - start_ns) // 1_000_000
    export_job_span(attrs, start_ns, end_ns)


def _handle_string_outcome(
    job_id: str, model: str, attempt: int, outcome: str, start_ns: int, end_ns: int
) -> tuple[bool, object]:
    """Turn a deferred/terminal string outcome from _run_with_lock into a result tuple."""
    if outcome == "deferred-qwen-busy":
        deferral_verdict = _record_deferral(job_id, "qwen-busy")
        return (False, deferral_verdict or outcome)
    _emit_telemetry(job_id, model, outcome, attempt, None, start_ns, end_ns, None, None)
    return (False, outcome)


def _finalize_success(
    *, job_id: str, host: str, options: dict[str, object], attempt: int,
    diff: str, response: dict[str, object], start_ns: int, end_ns: int,
) -> tuple[bool, object]:
    """Write the patch, compute stats/pinning, emit telemetry, and build the success result."""
    patch_path = _write_patch_file(job_id, diff)
    paths_touched, lines_changed = diff_stats(diff)
    running_digest, digest_matches = _check_model_pin(host, str(options["model"]), None)

    prompt_tokens = response.get("prompt_eval_count")
    completion_tokens = response.get("eval_count")
    prompt_tokens = int(prompt_tokens) if isinstance(prompt_tokens, int) else None
    completion_tokens = int(completion_tokens) if isinstance(completion_tokens, int) else None
    duration_ms = (end_ns - start_ns) // 1_000_000

    _clear_deferral_state(job_id)
    _emit_telemetry(
        job_id, str(options["model"]), "success", attempt, True,
        start_ns, end_ns, prompt_tokens, completion_tokens,
    )

    result = _build_result(
        patch_path=patch_path,
        patch_valid=True,
        files_touched=len(paths_touched),
        lines_changed=lines_changed,
        model=str(options["model"]),
        model_digest=running_digest,
        digest_matches=digest_matches,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
    )
    return (True, result)


def _run_generation(
    job: dict[str, object], payload: dict[str, object], resolved_files: list[Path], instruction: str,
    options: dict[str, object], host: str,
) -> tuple[bool, object]:
    """Guarded model call through result building. Assumes explain/admission/memory already checked."""
    job_id = str(job.get("id") or "")
    attempt = int(job.get("attempts") or 0)

    file_contents = _read_confined_files(resolved_files)
    prompt = _build_prompt(instruction, file_contents)
    timeout = _resolve_timeout(payload)

    start_ns = time.time_ns()
    outcome = _run_with_lock(host, str(options["model"]), prompt, options, timeout)
    end_ns = time.time_ns()

    if isinstance(outcome, str):
        return _handle_string_outcome(job_id, str(options["model"]), attempt, outcome, start_ns, end_ns)

    diff, response = outcome
    disk_verdict = _check_disk_guard()
    if disk_verdict is not None:
        deferral_verdict = _record_deferral(job_id, "low-disk")
        return (False, deferral_verdict or disk_verdict)

    return _finalize_success(
        job_id=job_id, host=host, options=options, attempt=attempt,
        diff=diff, response=response, start_ns=start_ns, end_ns=end_ns,
    )


def _run_guarded(job: dict[str, object], payload: dict[str, object]) -> tuple[bool, object]:
    """Guards + generation, run inside the outer exception boundary."""
    job_id = str(job.get("id") or "")
    files, instruction = _validate_payload(payload)
    resolved_files = resolve_input_files(files, _repo_root())

    options = _resolve_payload_options(payload)
    host = os.environ.get("QWEN_OLLAMA_HOST", DEFAULT_OLLAMA_HOST)

    if options["explain"]:
        report = _explain_report(resolved_files, instruction, str(options["model"]), options)
        return (True, report)

    admission_verdict = _check_admission_cap()
    if admission_verdict is not None:
        return (False, admission_verdict)

    memory_verdict = _check_memory_guard()
    if memory_verdict is not None:
        deferral_verdict = _record_deferral(job_id, "low-memory")
        return (False, deferral_verdict or memory_verdict)

    return _run_generation(job, payload, resolved_files, instruction, options, host)


def handle_qwen_patch(job: dict[str, object]) -> tuple[bool, object]:  # noqa - registered in handlers.REGISTRY
    """qwen_patch handler.

    job is the full job record; job["payload"] carries files, instruction,
    and optional model/system/temperature/max_tokens/explain/timeout keys.
    Never raises: the whole body runs inside one outer exception boundary
    that returns a masked, content-free string rather than letting a
    traceback (which could carry file content raised during prompt assembly)
    reach job_runtime's unmasked error path.
    """
    payload = dict(job.get("payload") or {})
    try:
        return _run_guarded(job, payload)
    except QwenGuardError as exc:
        return (False, mask_text(str(exc)))
    except Exception as exc:  # nosec B110 - exception boundary: convert to a masked, content-free terminal string per contract.redaction.exception_boundary
        return (False, f"terminal-internal-error: {mask_text(type(exc).__name__)}")
