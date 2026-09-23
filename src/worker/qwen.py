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
import posixpath
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from core.secrets import mask_text
from worker._helpers import get_repo_root, get_worker_state_dir
from worker.qwen_telemetry import export_job_span

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


class QwenTransientError(Exception):
    """A retryable transport failure (connection refused, timeout, HTTP 5xx,
    malformed response body).

    Deliberately distinct from QwenGuardError: str(exc) here is NOT an outcome
    string. It becomes a plain (unprefixed) failure per contract.retry_map, so
    job_runtime's normal attempts/backoff loop handles it rather than the
    terminal/deferred fast paths.
    """


TRANSIENT_OUTCOME_PREFIX = "ollama-request-failed"


def _repo_root() -> Path:
    return get_repo_root()


def _is_denied_name(path: Path) -> bool:
    """Denylist match on the file name, case-insensitively.

    macOS volumes are case-insensitive by default, so Credentials.ini and
    cert.PEM open the same bytes as their lowercase forms.
    """
    name = path.name.casefold()
    if name in DENYLIST_NAMES:
        return True
    if any(name.endswith(suf) for suf in DENYLIST_SUFFIXES):
        return True
    if "token" in name and name.endswith(".json"):
        return True
    if name.startswith(".env"):
        return True
    return False


def _has_git_segment(path: Path) -> bool:
    return any(part.casefold() == ".git" for part in path.parts)


def _is_within_allowlist(resolved: Path, root: Path) -> bool:
    for allowed in ALLOWLIST_DIRS:
        candidate = (root / allowed).resolve()
        if resolved.is_relative_to(candidate):
            return True
    return False


def _resolve_real_path(raw: str, root: Path) -> Path:
    candidate = Path(raw)
    p = candidate if candidate.is_absolute() else root / candidate
    try:
        return p.resolve()
    except OSError as exc:
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}") from exc


def _check_confined_file_stat(raw: str, real: Path) -> None:
    """Reject a non-regular-file path (e.g. a directory) or one over

    contract.input_confinement.max_file_bytes. max_file_bytes is an
    input_confinement threshold, so its violation is terminal-path-not-allowed,
    not terminal-prompt-too-large — that outcome is reserved for the separate
    assembled-prompt-vs-context-budget check. stat() inspects metadata only
    and never opens file contents.
    """
    try:
        st = real.stat()
    except OSError as exc:
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
    if st.st_size > THRESHOLDS.max_file_bytes:
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")


def _validate_one_input_file(raw: str, root: Path) -> Path:
    """Resolve and validate a single payload.files entry. See resolve_input_files."""
    real = _resolve_real_path(raw, root)
    if _has_git_segment(real):
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
    if _is_denied_name(real):
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
    if not _is_within_allowlist(real, root):
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")
    _check_confined_file_stat(raw, real)
    return real


def resolve_input_files(files: list[str], repo_root: Path) -> list[Path]:
    """Validate and resolve payload.files against the allowlist/denylist.

    Runs BEFORE any file is opened: resolves the real path (following
    symlinks), checks containment against the allowlisted directories,
    rejects denylisted names/suffixes, any path with a .git/ segment, any
    path that is not a regular file (e.g. a directory), and any file over
    contract.input_confinement.max_file_bytes. Raises
    QwenGuardError("terminal-path-not-allowed: <path>") on the first
    violation, before touching any later path in the list.
    """
    root = repo_root.resolve()
    return [_validate_one_input_file(raw, root) for raw in files]


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
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise QwenGuardError(f"http-error-{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc
    return _parse_json_object(raw)


def _parse_json_object(raw: bytes) -> dict[str, object]:
    """Decode a response body that must be a JSON object.

    A truncated or non-JSON body (a proxy error page, a connection cut
    mid-response) is transient: the same request can succeed next time.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError are both ValueError
        raise QwenTransientError("malformed response body") from exc
    if not isinstance(parsed, dict):
        raise QwenTransientError("response body is not a JSON object")
    return parsed


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
            raw = resp.read()
    except urllib.error.URLError as exc:  # HTTPError is a URLError subclass
        raise ConnectionError(str(exc.reason)) from exc
    return _parse_json_object(raw)


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


def _strip_ab_prefix(target: str) -> str:
    return target[2:] if target.startswith(("a/", "b/")) else target


def _unquote_path(target: str) -> str:
    """Drop the double quotes git puts around a path holding special characters."""
    if len(target) >= 2 and target[0] == target[-1] == '"':
        return target[1:-1]
    return target


def _parse_diff_header_target(line: str) -> str | None:
    """Parse a +++/--- header line into a bare target path, or None for /dev/null.

    A traditional diff may append a tab and a timestamp after the path.
    """
    target = _unquote_path(line[4:].split("\t", 1)[0].strip())
    if target == "/dev/null":
        return None
    return _strip_ab_prefix(target) or None


_RENAME_COPY_PREFIXES = ("rename from ", "rename to ", "copy from ", "copy to ")
_GIT_DIFF_HEADER = "diff --git "


def _extended_header_targets(line: str) -> list[str]:
    """Paths named by git's extended headers, which a pure rename or copy
    carries with no ---/+++ lines at all."""
    for prefix in _RENAME_COPY_PREFIXES:
        if line.startswith(prefix):
            return [_unquote_path(line[len(prefix):].strip())]
    if line.startswith(_GIT_DIFF_HEADER):
        rest = line[len(_GIT_DIFF_HEADER):].strip()
        left, sep, right = rest.partition(" b/")
        if sep:
            return [_strip_ab_prefix(_unquote_path(left)), _unquote_path(right)]
    return []


def _header_targets(line: str) -> list[str] | None:
    """Return the paths a diff header line names, or None when line is not a header."""
    if line.startswith(("+++ ", "--- ")):
        target = _parse_diff_header_target(line)
        return [target] if target else []
    if line.startswith((_GIT_DIFF_HEADER, *_RENAME_COPY_PREFIXES)):
        return _extended_header_targets(line)
    return None


def diff_stats(patch_text: str) -> tuple[list[str], int]:
    """Return (target paths, added+removed line count) parsed from a unified diff."""
    paths: list[str] = []
    lines_changed = 0
    for line in patch_text.splitlines():
        targets = _header_targets(line)
        if targets is not None:
            paths.extend(t for t in targets if t and t not in paths)
        elif line.startswith(("+", "-")):
            lines_changed += 1
    return paths, lines_changed


def _normalise_patch_target(target: str) -> str | None:
    """Return target as a normalised, casefolded repo-relative path.

    Returns None when the path is absolute or escapes the repo root. The
    comparison is casefolded because git apply on a case-insensitive volume
    writes Bin/qwen straight onto bin/qwen; ./ and inner .. segments are
    collapsed so ./bin/x and src/../bin/x cannot slip past a prefix check.
    """
    slashed = target.replace("\\", "/")
    if slashed.startswith("/"):
        return None
    norm = posixpath.normpath(slashed)
    if norm == ".." or norm.startswith("../"):
        return None
    return norm.casefold()


def _is_denied_patch_target(target: str) -> bool:
    norm = _normalise_patch_target(target)
    if norm is None:
        return True
    if ".git" in norm.split("/"):
        return True
    return any(f"{norm}/".startswith(prefix) for prefix in DENIED_PATCH_PREFIXES)


def check_patch_caps(patch_text: str) -> str | None:
    """Check patch_text against max_files/max_lines/denied prefixes.

    Returns None when the patch is within caps, else the exact terminal
    outcome string. git apply --check happily validates a patch that
    rewrites a denied path, so this is parsed independently. Denied
    prefixes are matched after normalisation and case folding, and any
    path with a .git segment is denied as well.
    """
    paths, lines_changed = diff_stats(patch_text)
    if len(paths) > THRESHOLDS.max_files or lines_changed > THRESHOLDS.max_lines:
        return "terminal-patch-too-broad"
    if any(_is_denied_patch_target(target) for target in paths):
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
    """Atomically create lock_path holding {pid, started_at}; False if it already exists.

    The payload is written to a private temp file first and then hard-linked
    into place. os.link fails with FileExistsError exactly as O_EXCL does,
    but the lock never exists in an empty, half-written state: an O_EXCL
    create followed by a separate write left a window in which a second
    thread would read an empty lock, judge it corrupt, and reclaim a live one.
    """
    import tempfile

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "started_at": time.time()}).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=str(lock_path.parent), prefix=".model.lock.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        try:
            os.link(tmp_name, str(lock_path))
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(tmp_name)


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


def _acquire_lock_with_wait(lock_path: Path, wait_ceiling_sec: float | None = None) -> bool:
    """Poll for the lock up to wait_ceiling_sec. Returns True on acquisition."""
    ceiling = THRESHOLDS.wait_ceiling_sec if wait_ceiling_sec is None else wait_ceiling_sec
    deadline = time.time() + ceiling
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


def _acquire_model_lock(job_id: str, wait_ceiling_sec: float | None = None) -> bool:
    """job_id-keyed public entry point over the real lock primitives above.

    _run_with_lock calls this (not _acquire_lock_with_wait directly) so it is
    the single seam that gates every model call; job_id is accepted for
    parity with _release_model_lock and future per-job diagnostics, but the
    lock itself is process-wide (contract.concurrency.scope: model call
    only), keyed by _lock_path(), not by job_id.
    """
    del job_id  # the lock is process-wide, not per-job; kept for API symmetry
    return _acquire_lock_with_wait(_lock_path(), wait_ceiling_sec)


def _release_model_lock(job_id: str) -> None:
    """job_id-keyed public entry point over _release_lock. See _acquire_model_lock."""
    del job_id
    _release_lock(_lock_path())


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


def _as_int(value: object, default: int) -> int:
    return int(value) if isinstance(value, (int, float, str)) else default


def _as_float(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float, str)) else default


def _record_deferral(job_id: str, reason: str) -> int:
    """Record one deferral under reason in the side-channel file; returns the

    running total deferral count for job_id (not a terminal-limit verdict —
    that is a separate decision made by _deferral_limit_verdict against the
    same on-disk state, so the raw count stays directly observable/testable).
    """
    state = _load_deferral_state(job_id)
    count = _as_int(state.get("count", 0), 0) + 1
    raw_reasons = state.get("reasons")
    reasons = dict(raw_reasons) if isinstance(raw_reasons, dict) else {}
    reasons[reason] = _as_int(reasons.get(reason, 0), 0) + 1
    first_deferred_at = _as_float(state.get("first_deferred_at"), time.time())
    new_state = {"count": count, "reasons": reasons, "first_deferred_at": first_deferred_at}
    path = _deferral_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new_state))
    return count


def _dominant_deferral_reason(job_id: str) -> str | None:
    state = _load_deferral_state(job_id)
    raw_reasons = state.get("reasons")
    reasons = raw_reasons if isinstance(raw_reasons, dict) else {}
    if not reasons:
        return None
    return str(max(reasons, key=lambda k: _as_int(reasons.get(k, 0), 0)))


def _deferral_limit_verdict(job_id: str, count: int) -> str | None:
    """Return the exact "terminal-deferral-limit: <dominant reason>" outcome

    string once job_id's deferral count or wall-clock age crosses the
    configured ceiling, else None. Reads first_deferred_at back off the same
    on-disk state _record_deferral just wrote.
    """
    state = _load_deferral_state(job_id)
    first_deferred_at = _as_float(state.get("first_deferred_at"), time.time())
    wallclock_min = (time.time() - first_deferred_at) / 60
    if count >= THRESHOLDS.deferral_ceiling_count or wallclock_min >= THRESHOLDS.deferral_wallclock_ceiling_min:
        reason = _dominant_deferral_reason(job_id)
        return f"terminal-deferral-limit: {reason}" if reason else "terminal-deferral-limit"
    return None


def _clear_deferral_state(job_id: str) -> None:
    """Delete the deferral side-channel file on any terminal exit for this job id.

    Called after the job's outcome is decided, so a failure here is logged
    and never changes that outcome.
    """
    if not job_id:
        return
    try:
        _deferral_path(job_id).unlink()
    except FileNotFoundError:  # nosec B110 - nothing to clear, e.g. a job that never deferred
        pass
    except OSError:
        _log.warning("qwen: could not delete deferral state for %s", job_id, exc_info=True)


# ---------------------------------------------------------------------------
# Model pinning and explain mode.
# ---------------------------------------------------------------------------


def _recorded_digest_path() -> Path:
    """Install-time digest record: a JSON object mapping model tag to its
    /api/tags digest, e.g. {"qwen2.5-coder:14b": "9ec8...849"}. Written once
    by the install step after the model is pulled; read on every job."""
    return get_worker_state_dir("qwen") / "model_digest.json"


def _load_recorded_digest(model: str) -> str | None:
    """Return the install-time digest recorded for model, or None if none was recorded."""
    path = _recorded_digest_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        _log.warning("qwen: unreadable model digest record at %s; treating %s as unpinned", path, model)
        return None
    value = raw.get(model) if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def _normalise_digest(digest: str) -> str:
    return digest.strip().lower().removeprefix("sha256:")


@dataclass(frozen=True)
class ModelPin:
    """Model identity check result.

    status is "match", "mismatch", "unpinned" (no install-time digest was
    recorded for this model) or "unverified" (the running digest could not
    be read). Only match/mismatch set matches_recorded; the others leave it
    None, per contract.result_schema.
    """

    running_digest: str | None
    matches_recorded: bool | None
    status: str


def _check_model_pin(host: str, model: str) -> ModelPin:
    """Compare the running model's digest with the install-time record.

    Never fails the job (contract.model_pinning.on_mismatch). Every state
    other than a match is logged at warning level, so an unpinned model is
    visible rather than passing silently.
    """
    recorded = _load_recorded_digest(model)
    running = _model_digest(host, model)
    if recorded is None:
        _log.warning("qwen: no install-time digest recorded for %s; model is unpinned", model)
        return ModelPin(running, None, "unpinned")
    if running is None:
        _log.warning("qwen: could not read the running digest for %s; pin unverified", model)
        return ModelPin(None, None, "unverified")
    matches = _normalise_digest(running) == _normalise_digest(recorded)
    if not matches:
        _log.warning("qwen: model digest drift for %s: recorded %s, running %s", model, recorded, running)
    return ModelPin(running, matches, "match" if matches else "mismatch")


@dataclass(frozen=True)
class GenerationOptions:
    """Resolved payload.model/system/temperature/max_tokens/explain, grouped

    so they travel as one value through the guard/transport/result chain
    instead of a wide parameter list or an untyped dict.
    """

    model: str
    system: str | None
    temperature: float
    max_tokens: int
    explain: bool


@dataclass(frozen=True)
class JobIdentity:
    """job_id/model/attempt travel together from _run_guarded through to
    telemetry and result-building; grouping them keeps call sites at or
    under the 5-parameter guideline."""

    job_id: str
    model: str
    attempt: int


def _explain_report(files: list[Path], instruction: str, options: GenerationOptions) -> dict[str, object]:
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
        "model": options.model,
        "options": {
            "system": options.system,
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
            "explain": options.explain,
        },
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
    """Read each resolved, already-confined file.

    resolve_input_files already rejected any file over max_file_bytes (an
    input_confinement threshold, terminal-path-not-allowed) before this is
    ever called, so no size check is repeated here.
    """
    contents: dict[str, str] = {}
    for f in files:
        try:
            contents[str(f)] = f.read_text(errors="replace")
        except OSError as exc:
            raise QwenGuardError(f"terminal-path-not-allowed: {f}") from exc
    return contents


def _estimate_prompt_tokens(prompt: str) -> int:
    """A conservative chars/4 estimate, matching explain_mode's own estimator."""
    return len(prompt) // 4


def _check_prompt_budget(prompt: str, options: GenerationOptions) -> str | None:
    """Return "terminal-prompt-too-large" if the assembled prompt exceeds the

    context budget (num_ctx minus the reserved max_tokens), else None. Fails
    loudly per contract.retry_map rather than silently truncating file
    content the user never approved truncating.
    """
    budget = THRESHOLDS.num_ctx - options.max_tokens
    if budget <= 0 or _estimate_prompt_tokens(prompt) > budget:
        return "terminal-prompt-too-large"
    return None


def _build_prompt(instruction: str, file_contents: dict[str, str]) -> str:
    parts = [f"Instruction: {instruction}", "", "Files:"]
    for path, content in file_contents.items():
        parts.append(f"--- {path} ---")
        parts.append(content)
    parts.append("")
    parts.append("Respond with a single unified diff in a ```diff fenced block.")
    return "\n".join(parts)


@dataclass(frozen=True)
class GenerationResult:
    """Every field of contract.json's result_schema, assembled by the caller

    and handed to _build_result as one value instead of eleven keyword
    arguments.
    """

    patch_path: Path
    patch_valid: bool
    files_touched: int
    lines_changed: int
    model: str
    model_digest: str | None
    digest_matches: bool | None
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int
    deferral_reasons: dict[str, int] | None = None


def _build_result(r: GenerationResult) -> dict[str, object]:
    return {
        "patch_path": str(r.patch_path),
        "patch_valid": r.patch_valid,
        "files_touched": r.files_touched,
        "lines_changed": r.lines_changed,
        "model": r.model,
        "model_digest": r.model_digest,
        "digest_matches_recorded": r.digest_matches,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "duration_ms": r.duration_ms,
        "deferral_reasons": r.deferral_reasons,
    }


def _call_ollama_generate(host: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    """Call /api/generate and classify the failure per contract.retry_map.

    HTTP 404 -> terminal-model-not-found (a missing model stays missing on
    retry). Any other HTTP status (5xx) and any connection-level failure
    (refused, timeout) are transient and re-raised as QwenTransientError so
    the caller reports a plain, retryable failure.

    _ollama_request translates urlopen's errors before they reach here:
    HTTPError becomes QwenGuardError("http-error-<code>") and URLError
    becomes ConnectionError. A socket timeout during resp.read() escapes
    as a bare TimeoutError, which the OSError branch covers.
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
    host: str, prompt: str, options: GenerationOptions, timeout: float
) -> tuple[str, dict[str, object]]:
    """Call the model, extract the diff, and validate it.

    Raises QwenGuardError (a terminal/deferred outcome string) or
    QwenTransientError (a plain, retryable failure) on failure.
    """
    body: dict[str, object] = {
        "model": options.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": options.temperature,
            "num_predict": options.max_tokens,
            "num_ctx": THRESHOLDS.num_ctx,
        },
    }
    if options.system:
        body["system"] = options.system
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


def _resolve_payload_options(payload: dict[str, object]) -> GenerationOptions:
    raw_system = payload.get("system")
    system = raw_system if isinstance(raw_system, str) else None
    return GenerationOptions(
        model=str(payload.get("model") or DEFAULT_MODEL_TAG),
        system=system,
        temperature=_as_float(payload.get("temperature"), 0.2),
        max_tokens=_as_int(payload.get("max_tokens"), 4096),
        explain=bool(payload.get("explain") or False),
    )


def _resolve_timeout(payload: dict[str, object]) -> float:
    """payload["timeout"] is only injected by job_runtime for a positive resolved timeout_sec."""
    raw = payload.get("timeout")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return THRESHOLDS.ollama_request_timeout_sec


def _run_with_lock(
    job_id: str, host: str, prompt: str, options: GenerationOptions, timeout: float
) -> tuple[str, dict[str, object]] | str:
    """Acquire the lock, run the model call, release in finally.

    Goes through _acquire_model_lock/_release_model_lock (not the lower-level
    _acquire_lock_with_wait/_release_lock directly) so those job_id-keyed
    names are the single seam that gates every model call — mocking either
    one to force lock contention must be sufficient to prove the model is
    never invoked while the lock is held.

    Returns (diff, response) on success, or a string outcome: a
    "terminal-"/"deferred-" prefixed string from QwenGuardError, or a PLAIN
    string from QwenTransientError, prefixed TRANSIENT_OUTCOME_PREFIX —
    connection-refused, timeout, and HTTP 5xx are contract.retry_map
    "plain" outcomes, so job_runtime's ordinary attempts/backoff loop must
    see them, not the terminal/deferred fast paths. The fixed prefix keeps
    the outcome non-empty even when the exception message is. Masking
    happens once, at handle_qwen_patch's boundary.
    """
    if not _acquire_model_lock(job_id):
        return "deferred-qwen-busy"
    try:
        return _generate_and_validate_patch(host, prompt, options, timeout)
    except QwenGuardError as exc:
        return str(exc)
    except QwenTransientError as exc:
        return f"{TRANSIENT_OUTCOME_PREFIX}: {exc}"
    finally:
        _release_model_lock(job_id)


@dataclass(frozen=True)
class _TelemetryEvent:
    """The fields _emit_telemetry needs, grouped to keep its signature short."""

    identity: JobIdentity
    outcome: str
    patch_valid: bool | None
    start_ns: int
    end_ns: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    pin: ModelPin | None = None


def _telemetry_attrs(event: _TelemetryEvent) -> dict[str, object]:
    """Span attributes for event, every string value masked.

    job_id, model and outcome can all carry payload- or model-derived text
    (a transient outcome embeds the transport's error message), so the
    masking is applied to the whole mapping rather than per field.
    """
    attrs: dict[str, object] = {
        "qwen.job_id": event.identity.job_id,
        "qwen.job_type": JOB_TYPE,
        "qwen.model": event.identity.model,
        "qwen.outcome": event.outcome,
        "qwen.attempt": event.identity.attempt,
        "qwen.patch_valid": event.patch_valid,
    }
    if event.prompt_tokens is not None:
        attrs["qwen.prompt_tokens"] = event.prompt_tokens
    if event.completion_tokens is not None:
        attrs["qwen.completion_tokens"] = event.completion_tokens
    if event.pin is not None:
        attrs["qwen.model_pin"] = event.pin.status
        attrs["qwen.model_digest"] = event.pin.running_digest
    attrs["qwen.generation_duration_ms"] = (event.end_ns - event.start_ns) // 1_000_000
    return {key: mask_text(value) if isinstance(value, str) else value for key, value in attrs.items()}


def _emit_telemetry(event: _TelemetryEvent) -> None:
    # export_job_span is imported at module scope (not locally) specifically
    # so mock.patch("worker.qwen.export_job_span", ...) — patch where the
    # name is used, per house convention — actually intercepts this call.
    try:
        attrs = _telemetry_attrs(event)
        export_job_span(attrs, event.start_ns, event.end_ns)
    except Exception:  # nosec B110 - contract.telemetry.failure_is_nonfatal: export must never affect job outcome, independent of export_job_span's own internal guard
        _log.debug("qwen: telemetry export raised (non-fatal)", exc_info=True)


def _handle_string_outcome(
    identity: JobIdentity, outcome: str, start_ns: int, end_ns: int
) -> tuple[bool, object]:
    """Turn a deferred/terminal string outcome from _run_with_lock into a result tuple."""
    if outcome == "deferred-qwen-busy":
        count = _record_deferral(identity.job_id, "qwen-busy")
        limit_verdict = _deferral_limit_verdict(identity.job_id, count)
        return (False, limit_verdict or outcome)
    _emit_telemetry(_TelemetryEvent(identity, outcome, None, start_ns, end_ns))
    return (False, outcome)


def _finalize_success(
    identity: JobIdentity, host: str, diff: str, response: dict[str, object], start_ns: int, end_ns: int
) -> tuple[bool, object]:
    """Write the patch, compute stats/pinning, emit telemetry, and build the success result."""
    patch_path = _write_patch_file(identity.job_id, diff)
    paths_touched, lines_changed = diff_stats(diff)
    pin = _check_model_pin(host, identity.model)

    prompt_tokens = response.get("prompt_eval_count")
    completion_tokens = response.get("eval_count")
    prompt_tokens = int(prompt_tokens) if isinstance(prompt_tokens, int) else None
    completion_tokens = int(completion_tokens) if isinstance(completion_tokens, int) else None
    duration_ms = (end_ns - start_ns) // 1_000_000

    _emit_telemetry(
        _TelemetryEvent(identity, "success", True, start_ns, end_ns, prompt_tokens, completion_tokens, pin)
    )

    result = _build_result(
        GenerationResult(
            patch_path=patch_path,
            patch_valid=True,
            files_touched=len(paths_touched),
            lines_changed=lines_changed,
            model=identity.model,
            model_digest=pin.running_digest,
            digest_matches=pin.matches_recorded,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
    )
    return (True, result)


def _run_generation(
    job: dict[str, object], payload: dict[str, object], resolved_files: list[Path], instruction: str,
    options: GenerationOptions, host: str,
) -> tuple[bool, object]:
    """Guarded model call through result building. Assumes explain/admission/memory already checked."""
    identity = JobIdentity(
        job_id=str(job.get("id") or ""), model=options.model, attempt=_as_int(job.get("attempts"), 0)
    )

    file_contents = _read_confined_files(resolved_files)
    prompt = _build_prompt(instruction, file_contents)
    timeout = _resolve_timeout(payload)

    budget_verdict = _check_prompt_budget(prompt, options)
    if budget_verdict is not None:
        return (False, budget_verdict)

    start_ns = time.time_ns()
    outcome = _run_with_lock(identity.job_id, host, prompt, options, timeout)
    end_ns = time.time_ns()

    if isinstance(outcome, str):
        return _handle_string_outcome(identity, outcome, start_ns, end_ns)

    diff, response = outcome
    disk_verdict = _check_disk_guard()
    if disk_verdict is not None:
        count = _record_deferral(identity.job_id, "low-disk")
        limit_verdict = _deferral_limit_verdict(identity.job_id, count)
        return (False, limit_verdict or disk_verdict)

    return _finalize_success(identity, host, diff, response, start_ns, end_ns)


def _run_guarded(job: dict[str, object], payload: dict[str, object]) -> tuple[bool, object]:
    """Guards + generation, run inside the outer exception boundary."""
    job_id = str(job.get("id") or "")
    files, instruction = _validate_payload(payload)
    resolved_files = resolve_input_files(files, _repo_root())

    options = _resolve_payload_options(payload)
    host = os.environ.get("QWEN_OLLAMA_HOST", DEFAULT_OLLAMA_HOST)

    if options.explain:
        report = _explain_report(resolved_files, instruction, options)
        return (True, report)

    admission_verdict = _check_admission_cap()
    if admission_verdict is not None:
        return (False, admission_verdict)

    memory_verdict = _check_memory_guard()
    if memory_verdict is not None:
        count = _record_deferral(job_id, "low-memory")
        limit_verdict = _deferral_limit_verdict(job_id, count)
        return (False, limit_verdict or memory_verdict)

    return _run_generation(job, payload, resolved_files, instruction, options, host)


def handle_qwen_patch(job: dict[str, object]) -> tuple[bool, object]:  # noqa - registered in handlers.REGISTRY
    """qwen_patch handler.

    job is the full job record; job["payload"] carries files, instruction,
    and optional model/system/temperature/max_tokens/explain/timeout keys.
    Never raises: the whole body runs inside one outer exception boundary
    that returns a masked, content-free string rather than letting a
    traceback (which could carry file content raised during prompt assembly)
    reach job_runtime's unmasked error path.

    The boundary is also the single exit every outcome passes through, so
    two rules are applied here once rather than at each return site: every
    failure string is masked (job_runtime writes it to last_error verbatim),
    and the deferral side-channel file is deleted on success and on every
    terminal-* exit (contract.deferral_bound.cleanup).
    """
    raw_payload = job.get("payload")
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    try:
        ok, out = _run_guarded(job, payload)
    except QwenGuardError as exc:
        ok, out = False, str(exc)
    except Exception as exc:  # nosec B110 - exception boundary: convert to a content-free terminal string per contract.redaction.exception_boundary
        ok, out = False, f"terminal-internal-error: {type(exc).__name__}"
    if not ok:
        out = mask_text(str(out))
    if ok or str(out).startswith("terminal-"):
        _clear_deferral_state(str(job.get("id") or ""))
    return ok, out
