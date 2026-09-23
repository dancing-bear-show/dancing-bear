"""qwen_patch job handler: local Ollama-backed code-patch generation.

Registered as ``REGISTRY["qwen_patch"] = handle_qwen_patch`` in
``worker.handlers``. Given a set of repo-relative files and a natural-language
instruction, prompts a local Ollama model (default ``qwen2.5-coder:14b``) to
produce a unified diff, validates the diff with ``git apply --check``, and
writes it to a patch file under ``core.paths.output_dir("qwen")``. The patch
is never applied by this handler.

Guard order (contract.json): the job id is validated first (it becomes a
file name under the qwen state and patch dirs), then the payload shape and
every option are validated (no disk access), then input confinement runs
(before any file is opened and before the concurrency lock), then the memory
precheck, then the lock/model call, then patch validation/caps/disk precheck.
See ``handle_qwen_patch`` for the full sequence.

Outcome strings (the handler's second return value on failure):

* ``terminal-invalid-job-id`` - job id is not a safe file-name component
* ``terminal-invalid-payload: <reason>``
* ``terminal-path-not-allowed: <path>`` - input confinement
* ``terminal-lane-over-capacity`` - admission cap
* ``terminal-prompt-too-large`` - assembled prompt exceeds the context budget
* ``terminal-model-not-found`` - HTTP 404 from Ollama
* ``terminal-ollama-request-rejected: http-error-<code>`` - any other HTTP
  status that retrying cannot fix (400, 401, 403, ...)
* ``terminal-no-diff-found`` / ``terminal-patch-does-not-apply``
* ``terminal-patch-too-broad`` - caps, denied targets, binary or unparseable
  path headers
* ``terminal-deferral-limit[: <reason>]``
* ``terminal-internal-error: <exception type>``
* ``deferred-low-memory`` / ``deferred-qwen-busy`` / ``deferred-low-disk``
* ``ollama-request-failed: <detail>`` - plain, retryable transport failure

Every string derived from payload content or model output that reaches the
result (success, failure or explain report), a log line or telemetry is
masked via ``core.secrets.mask_text`` first. The
prompt itself is never persisted; the only place file contents reach disk is
inside the generated patch artifact, which lives outside the checkout.
"""

from __future__ import annotations

import json
import logging
import math
import os
import posixpath
import re
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from core.secrets import mask_text
from worker._helpers import get_repo_root, get_worker_state_dir
from worker.qwen_telemetry import export_in_background, export_job_metrics, export_job_span

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
    # payload.files entries accepted, checked on the raw list before any
    # path is resolved, stat'd or opened. At num_ctx 8192 the whole prompt
    # is ~32 KiB of text (chars/4), so a request naming more than 32 files
    # cannot carry a useful share of each one; the cap bounds the per-file
    # confinement work that runs before the prompt-budget guard can refuse.
    max_input_files: int = 32
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
INVALID_JOB_ID_OUTCOME = "terminal-invalid-job-id"

# A job id becomes a file name (deferral state, patch artifact), and
# `worker enqueue --id` accepts any string. Strict allowlist: a leading
# alphanumeric rules out "", ".", ".." and hidden names, and the body admits
# no path separator of any kind.
_SAFE_JOB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def is_safe_job_id(job_id: object) -> bool:
    """True when job_id can be used as a single file-name component."""
    return isinstance(job_id, str) and _SAFE_JOB_ID_RE.fullmatch(job_id) is not None


def _job_file_name(job_id: str, suffix: str) -> str:
    """<job_id><suffix>; raises QwenGuardError(INVALID_JOB_ID_OUTCOME) for an unsafe id."""
    if not is_safe_job_id(job_id):
        raise QwenGuardError(INVALID_JOB_ID_OUTCOME)
    return f"{job_id}{suffix}"


def job_scoped_path(base: Path, job_id: str, suffix: str) -> Path:
    """Return base/<job_id><suffix>, the path every job-scoped read and write uses.

    Raises QwenGuardError(INVALID_JOB_ID_OUTCOME) for an id that fails
    is_safe_job_id, and for a name that is already a symlink - even one
    pointing at another job's file in the same directory, which a
    resolved-parent check alone would admit. The resolved parent must also
    be base itself. A symlink planted after this check is handled by the
    writer: _write_job_file replaces the name rather than following it.
    """
    candidate = base / _job_file_name(job_id, suffix)
    if candidate.is_symlink() or candidate.resolve().parent != base.resolve():
        raise QwenGuardError(INVALID_JOB_ID_OUTCOME)
    return candidate


def _write_job_file(path: Path, text: str) -> None:
    """Write text to a job-scoped path atomically, never through a symlink.

    The bytes go to a private temp file in the same directory, which
    os.replace then renames over path. A rename replaces whatever directory
    entry sits at path - a symlink included - instead of writing into its
    target, so a link planted between job_scoped_path's check and this write
    is swapped out rather than followed, and a reader never sees a
    half-written file.
    """
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        _unlink_quietly(Path(tmp_name))
        raise


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
    """True when resolved sits under an allowlisted directory INSIDE root.

    Resolving an allowlist directory follows a symlink, so a checkout whose
    src/ points at /sensitive would otherwise move the trust boundary itself
    and admit /sensitive/anything. Both the directory and the file must
    therefore resolve under the resolved repo root.
    """
    real_root = root.resolve()
    if not resolved.is_relative_to(real_root):
        return False
    for allowed in ALLOWLIST_DIRS:
        candidate = (real_root / allowed).resolve()
        if candidate.is_relative_to(real_root) and resolved.is_relative_to(candidate):
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


def _check_path_policy(raw: str, real: Path, root: Path) -> None:
    """Apply the .git-segment, denylist and allowlist rules to a real path.

    Shared by the pre-open check (on the resolved path) and the post-open
    check (on the path the kernel reports for the opened descriptor), so
    both sides of the open enforce the same policy.
    """
    if _has_git_segment(real) or _is_denied_name(real) or not _is_within_allowlist(real, root):
        raise QwenGuardError(f"terminal-path-not-allowed: {raw}")


def _validate_one_input_file(raw: str, root: Path) -> Path:
    """Resolve and validate a single payload.files entry. See resolve_input_files."""
    real = _resolve_real_path(raw, root)
    _check_path_policy(raw, real, root)
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

    This pre-open pass fixes the ordering (a disallowed path is rejected as
    not-allowed even when it does not exist) but cannot by itself stop a
    swap between check and open. _read_confined_bytes closes that gap by
    re-running the same policy on the descriptor it actually reads.

    Duplicates collapse, preserving first-seen order: identical strings
    before anything is resolved, then spellings that resolve to the same
    file (src/a.py and ./src/a.py), so each file is read and prompted once.
    """
    root = repo_root.resolve()
    resolved = [_validate_one_input_file(raw, root) for raw in dict.fromkeys(files)]
    return list(dict.fromkeys(resolved))


def _validate_payload(payload: dict[str, object]) -> tuple[list[str], str]:
    """Validate required payload fields. Raises QwenGuardError on failure.

    The files count is a payload-shape error (terminal-invalid-payload), not
    a confinement verdict: no single path is at fault, and it is checked on
    the raw list so an oversized one is refused without touching the disk.
    """
    files = payload.get("files")
    if isinstance(files, list) and len(files) > THRESHOLDS.max_input_files:
        raise QwenGuardError(f"terminal-invalid-payload: files must list at most {THRESHOLDS.max_input_files} entries")
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


def _nearest_existing_ancestor(path: Path) -> Path:
    """path itself, or its closest ancestor that exists; path if none does.

    The patch directory is created on the first successful write, so on a
    first run neither it nor its parent may exist yet. Measuring the nearest
    existing ancestor reads the filesystem the directory will be created on,
    without creating anything.
    """
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path


def _free_disk_bytes(path: Path) -> int | None:
    """Return free bytes on the filesystem that holds (or will hold) path.

    None only when even the nearest existing ancestor cannot be measured;
    the disk guard then fails open per contract.disk_guard.
    """
    import shutil

    try:
        return shutil.disk_usage(str(_nearest_existing_ancestor(path))).free
    except OSError:
        return None


_LANE_FOLDERS = ("pending", "processing")


def _lane_depth(job_type: str) -> int:
    """Count every pending+processing job file of job_type (this type only).

    Deliberately NOT queue_ops.list_pending: that returns only jobs that are
    due now, and every deferral sets a future not_before, so deferred qwen
    jobs - exactly the backlog this cap exists to bound - would vanish from
    the count. Each job file's type is read from the file itself.
    """
    from core.fileutil import safe_load_json
    from worker import queue_ops

    folders = queue_ops._ensure_dirs(queue_ops.QUEUE_ROOT)
    count = 0
    for folder in _LANE_FOLDERS:
        for path in queue_ops._list_job_paths(folders[folder]):
            data = safe_load_json(path, default={})
            if isinstance(data, dict) and str(data.get("type")) == job_type:
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


def _pid_is_worker(pid: int) -> bool | None:
    """Whether pid's command line names a worker process.

    Tri-state: True / False when ps answered, None when it could not (ps
    missing, timed out, or a nonzero exit). None is "unknown", never "not a
    worker": callers must not treat an unreadable process table as
    permission to reclaim a lock.
    """
    import subprocess  # nosec B404 - subprocess imported deliberately for ps; call site below carries its own review

    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv with an int pid, no shell
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
        )
    except Exception:  # nosec B110 - unreadable process table: report unknown, the caller retains the lock
        return None
    if result.returncode != 0:
        return None
    return "worker" in result.stdout


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


class UnsupportedPatchError(ValueError):
    """A patch the caps check cannot vouch for: a binary patch, or a
    path-bearing header whose paths cannot be parsed. Always
    terminal-patch-too-broad (fail closed)."""


# git's C-style name quoting (quote.c: sq_lookup / unquote_c_style).
_GIT_QUOTE_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
_OCTAL_DIGITS = frozenset("01234567")


def _unescape_git_char(text: str, i: int, out: bytearray) -> int:
    """Decode the escape starting at text[i] (just past the backslash) into
    out; return the index after it."""
    esc = text[i : i + 1]
    if esc in _GIT_QUOTE_ESCAPES:
        out.append(_GIT_QUOTE_ESCAPES[esc])
        return i + 1
    digits = text[i : i + 3]
    if len(digits) == 3 and digits[0] in "0123" and set(digits) <= _OCTAL_DIGITS:
        out.append(int(digits, 8))
        return i + 3
    raise UnsupportedPatchError(f"bad escape in quoted name: {text!r}")


def _parse_git_quoted(text: str) -> tuple[str, int]:
    """Parse the git-quoted name that opens text (text[0] == '"').

    Returns (unquoted name, index just past the closing quote). Octal
    escapes are raw bytes (\\303\\251 is UTF-8 for an accented e), so the
    name is built as bytes and decoded once at the end.
    """
    out = bytearray()
    i = 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return out.decode("utf-8", errors="replace"), i + 1
        if ch == "\\":
            i = _unescape_git_char(text, i + 1, out)
        else:
            out += ch.encode("utf-8")
            i += 1
    raise UnsupportedPatchError(f"unterminated quoted name: {text!r}")


def _header_name(raw: str) -> str:
    """Decode one header name: git-quoted when it opens with a double quote, else literal."""
    if not raw.startswith('"'):
        return raw
    name, end = _parse_git_quoted(raw)
    if end != len(raw):
        raise UnsupportedPatchError(f"trailing text after quoted name: {raw!r}")
    return name


def _strip_patch_prefix(name: str) -> str:
    """Drop the leading path component, exactly as git apply's default -p1 does.

    Not just a/ and b/: git apply strips whatever the first component is, so
    +++ x/bin/qwen writes bin/qwen. A name with nothing left after the strip
    is unparseable.
    """
    _, sep, rest = name.partition("/")
    if not sep or not rest:
        raise UnsupportedPatchError(f"no path after the -p1 prefix: {name!r}")
    return rest


def _parse_diff_header_target(line: str) -> str | None:
    """Parse a +++/--- header line into a bare target path, or None for /dev/null.

    A traditional diff may append a tab and a timestamp after the path.
    """
    raw = line[4:].split("\t", 1)[0].strip()
    if raw == "/dev/null":
        return None
    return _strip_patch_prefix(_header_name(raw))


_RENAME_COPY_PREFIXES = ("rename from ", "rename to ", "copy from ", "copy to ")
_GIT_DIFF_HEADER = "diff --git "


def _split_git_diff_header(rest: str) -> tuple[str, str]:
    """Split the two (possibly quoted) names of a diff --git header."""
    if rest.startswith('"'):
        _, end = _parse_git_quoted(rest)
        if rest[end : end + 1] != " ":
            raise UnsupportedPatchError(f"malformed diff --git header: {rest!r}")
        return rest[:end], rest[end + 1 :]
    if rest.endswith('"'):
        left, sep, right = rest.partition(' "')
        if not sep:
            raise UnsupportedPatchError(f"malformed diff --git header: {rest!r}")
        return left, f'"{right}'
    left, sep, right = rest.partition(" b/")
    if not sep:
        raise UnsupportedPatchError(f"unparseable diff --git header: {rest!r}")
    return left, f"b/{right}"


def _extended_header_targets(line: str) -> list[str]:
    """Paths named by git's extended headers, which a pure rename or copy
    carries with no ---/+++ lines at all.

    rename/copy names carry no a/ b/ prefix (git apply strips p_value - 1
    components from them, i.e. none), so only the diff --git names are
    prefix-stripped.
    """
    for prefix in _RENAME_COPY_PREFIXES:
        if line.startswith(prefix):
            return [_header_name(line[len(prefix):].strip())]
    left, right = _split_git_diff_header(line[len(_GIT_DIFF_HEADER):].strip())
    return [_strip_patch_prefix(_header_name(left)), _strip_patch_prefix(_header_name(right))]


def _header_targets(line: str) -> list[str] | None:
    """Return the paths a diff header line names, or None when line is not a header.

    Raises UnsupportedPatchError when line is a path-bearing header whose
    paths cannot be parsed.
    """
    if line.startswith(("+++ ", "--- ")):
        target = _parse_diff_header_target(line)
        return [target] if target else []
    if line.startswith((_GIT_DIFF_HEADER, *_RENAME_COPY_PREFIXES)):
        return _extended_header_targets(line)
    return None


_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_BINARY_PATCH_RE = re.compile(r"^(?:GIT binary patch|Binary files .* differ)$")


def _hunk_line_counts(line: str) -> tuple[int, int] | None:
    """(old, new) line counts from a hunk header, or None when line is not one."""
    match = _HUNK_HEADER_RE.match(line)
    if match is None:
        return None
    old, new = match.group(1), match.group(2)
    return int(old if old is not None else 1), int(new if new is not None else 1)


def _consume_hunk_line(line: str, remaining: tuple[int, int]) -> tuple[int, int, int] | None:
    """Account for one hunk body line: (old left, new left, changed), or None
    when line cannot belong to the hunk (it then ends the hunk early)."""
    old, new = remaining
    marker = line[:1]
    if marker in (" ", ""):
        return old - 1, new - 1, 0
    if marker == "-":
        return old - 1, new, 1
    if marker == "+":
        return old, new - 1, 1
    if marker == "\\":  # "\ No newline at end of file"
        return old, new, 0
    return None


def diff_stats(patch_text: str) -> tuple[list[str], int]:
    """Return (target paths, added+removed line count) parsed from a unified diff.

    Hunk bodies are consumed by their @@ line counts, as git apply does, so
    a removed line that reads "-- x" (shown as "--- x") is counted as a
    change rather than mistaken for a file header. Raises
    UnsupportedPatchError for a binary patch or an unparseable path header.
    """
    paths: list[str] = []
    lines_changed = 0
    remaining = (0, 0)
    for line in patch_text.splitlines():
        if remaining[0] > 0 or remaining[1] > 0:
            consumed = _consume_hunk_line(line, remaining)
            if consumed is not None:
                remaining = consumed[:2]
                lines_changed += consumed[2]
                continue
            remaining = (0, 0)
        counts = _hunk_line_counts(line)
        if counts is not None:
            remaining = counts
            continue
        if _BINARY_PATCH_RE.match(line):
            raise UnsupportedPatchError("binary patch")
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
    path with a .git segment is denied as well. A binary patch, or any
    path-bearing header that cannot be parsed, is too broad by definition:
    the check cannot see where it writes (fail closed).
    """
    try:
        paths, lines_changed = diff_stats(patch_text)
    except UnsupportedPatchError:
        return "terminal-patch-too-broad"
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
    """One acquisition of the lock, as recorded in the lock file.

    token is unique per acquisition. pid alone cannot tell two acquisitions
    apart - a worker runs several qwen handlers as threads of one process -
    so equality (and therefore every compare-and-delete) includes it. The
    pid/started_at pair still drives the staleness verdict, exactly as
    qwen-admin reads it. A lock file written before the token existed
    reads back with token None.
    """

    pid: int
    started_at: float
    token: str | None = None


def _read_lock_holder(lock_path: Path) -> _LockHolder | None:
    try:
        raw = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    try:
        token = raw.get("token")
        return _LockHolder(
            pid=int(raw["pid"]),
            started_at=float(raw["started_at"]),
            token=token if isinstance(token, str) else None,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _lock_verdict(holder: _LockHolder, now: float) -> str:
    """Return "absent"|"active"|"SUSPECT"|"STALE" for an existing lock holder."""
    if not _pid_alive(holder.pid):
        return "STALE"
    age = now - holder.started_at
    if age <= THRESHOLDS.stale_ceiling_sec:
        return "active"
    return "SUSPECT"


def _try_acquire_lock(lock_path: Path) -> _LockHolder | None:
    """Atomically create lock_path holding {pid, started_at, token}.

    Returns the holder record written - the caller's proof of ownership,
    handed back to _release_lock - or None if the lock already exists.
    Ownership travels with the acquisition rather than living in a
    per-path table: with several handler threads in one process, a table
    keyed by lock path let a later acquisition overwrite an earlier one's
    entry, and the earlier thread's release then deleted the newer lock.

    The payload is written to a private temp file first and then hard-linked
    into place. os.link fails with FileExistsError exactly as O_EXCL does,
    but the lock never exists in an empty, half-written state: an O_EXCL
    create followed by a separate write left a window in which a second
    thread would read an empty lock, judge it corrupt, and reclaim a live one.
    """
    import tempfile

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = _LockHolder(pid=os.getpid(), started_at=time.time(), token=uuid.uuid4().hex)
    payload = json.dumps({"pid": holder.pid, "started_at": holder.started_at, "token": holder.token})
    fd, tmp_name = tempfile.mkstemp(dir=str(lock_path.parent), prefix=".model.lock.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload.encode("utf-8"))
        try:
            os.link(tmp_name, str(lock_path))
        except FileExistsError:
            return None
        return holder
    finally:
        os.unlink(tmp_name)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:  # nosec B110 - already gone is the state we wanted
        pass


def _restore_lock(tombstone: Path, lock_path: Path) -> None:
    """Put a lock we should not have taken back under its real name.

    os.link, not os.rename: link refuses to overwrite, so if a third job
    acquired the (briefly absent) lock in between, its lock is kept and the
    one we moved aside is dropped - the alternative would delete a live
    holder's lock a second time.
    """
    try:
        os.link(str(tombstone), str(lock_path))
    except FileExistsError:
        _log.warning("qwen: %s was re-acquired while a mistaken reclaim was undone", lock_path)
    finally:
        _unlink_quietly(tombstone)


def _remove_lock_if_held_by(lock_path: Path, expected: _LockHolder | None) -> bool:
    """Compare-and-delete: remove lock_path only if it still records expected.

    Inspect-then-unlink is a race: between reading a stale holder and the
    unlink, another job can reclaim that lock and acquire its own, and the
    unlink would then delete the NEW holder's lock. Instead the lock is
    first renamed to a name unique to this attempt - an atomic step that
    takes exactly one file out of play - and the file actually taken is
    re-read. Only if it is still the holder that was judged removable is it
    deleted; otherwise it belongs to someone else and is put back.

    (An O_EXCL "reclaim mutex" sidecar was rejected: acquire and release do
    not take it, so a release+acquire could still land between the re-read
    and the unlink.)

    Returns True when the lock is gone (removed here, or already absent).
    """
    tombstone = lock_path.with_name(f".{lock_path.name}.reclaim.{uuid.uuid4().hex}")
    try:
        os.rename(str(lock_path), str(tombstone))
    except FileNotFoundError:
        return True
    if _read_lock_holder(tombstone) == expected:
        _unlink_quietly(tombstone)
        return True
    _restore_lock(tombstone, lock_path)
    return False


def _reclaim_lock(lock_path: Path, expected: _LockHolder | None) -> _LockHolder | None:
    """Remove a STALE/reclaimable lock still held by expected, then re-attempt acquisition.

    expected is None for a lock that was unreadable or corrupt when inspected.
    Returns the new holder record on acquisition, else None.
    """
    if not _remove_lock_if_held_by(lock_path, expected):
        return None
    return _try_acquire_lock(lock_path)


def _suspect_is_reclaimable(holder: _LockHolder) -> bool:
    """SUSPECT rule: reclaim only when the holder is confirmed not to be a
    worker process, or the lane is empty. An unknown answer from ps keeps
    the lock (fail safe)."""
    is_worker = _pid_is_worker(holder.pid)
    if is_worker is None:
        _log.warning("qwen: cannot confirm whether lock holder pid %s is a worker; keeping its lock", holder.pid)
        return False
    return not is_worker or _lane_depth(JOB_TYPE) == 0


def _handle_existing_lock(lock_path: Path) -> _LockHolder | None:
    """Inspect an existing lock; reclaim if STALE or reclaimable SUSPECT.

    Returns the new holder record if this call acquired the lock, else None.
    """
    holder = _read_lock_holder(lock_path)
    if holder is None:
        # Unreadable/corrupt lock file: treat as stale and reclaim.
        return _reclaim_lock(lock_path, None)
    verdict = _lock_verdict(holder, time.time())
    if verdict == "STALE" or (verdict == "SUSPECT" and _suspect_is_reclaimable(holder)):
        return _reclaim_lock(lock_path, holder)
    return None


def _acquire_lock_with_wait(lock_path: Path, wait_ceiling_sec: float | None = None) -> _LockHolder | None:
    """Poll for the lock up to wait_ceiling_sec. Returns the holder record on acquisition."""
    ceiling = THRESHOLDS.wait_ceiling_sec if wait_ceiling_sec is None else wait_ceiling_sec
    deadline = time.time() + ceiling
    acquired = _try_acquire_lock(lock_path)
    while acquired is None and time.time() < deadline:
        acquired = _handle_existing_lock(lock_path)
        if acquired is None:
            time.sleep(THRESHOLDS.lock_poll_interval_sec)
    return acquired


def _release_lock(lock_path: Path, mine: _LockHolder) -> None:
    """Release the acquisition recorded by mine, compare-and-delete like a reclaim.

    If that acquisition was reclaimed out from under us and someone else -
    another thread of this same process included - now holds lock_path,
    the token differs and their lock is left alone.
    """
    if not _remove_lock_if_held_by(lock_path, mine):
        _log.warning("qwen: %s is held by another job; leaving it in place on release", lock_path)


def _acquire_model_lock(job_id: str, wait_ceiling_sec: float | None = None) -> _LockHolder | None:
    """job_id-keyed public entry point over the real lock primitives above.

    _run_with_lock calls this (not _acquire_lock_with_wait directly) so it is
    the single seam that gates every model call; job_id is accepted for
    parity with _release_model_lock and future per-job diagnostics, but the
    lock itself is process-wide (contract.concurrency.scope: model call
    only), keyed by _lock_path(), not by job_id. Returns the acquisition's
    holder record, which the caller hands back to _release_model_lock, or
    None when the lock could not be taken.
    """
    del job_id  # the lock is process-wide, not per-job; kept for API symmetry
    return _acquire_lock_with_wait(_lock_path(), wait_ceiling_sec)


def _release_model_lock(job_id: str, holder: _LockHolder) -> None:
    """job_id-keyed public entry point over _release_lock. See _acquire_model_lock."""
    del job_id
    _release_lock(_lock_path(), holder)


# ---------------------------------------------------------------------------
# Deferral bound — a side-channel file, since q.retry() reloads the job from
# disk and never persists an in-memory payload mutation.
# ---------------------------------------------------------------------------


_DEFERRAL_SUFFIX = ".json"


def _deferral_path(job_id: str) -> Path:
    return job_scoped_path(_deferral_dir(), job_id, _DEFERRAL_SUFFIX)


def patch_path_for_job(job_id: str) -> Path:
    """Where job_id's patch artifact lives (contract.result_schema.patch_path).

    Shared with bin/qwen --apply so both sides validate the id the same way.
    """
    return job_scoped_path(_patch_dir(), job_id, ".patch")


def _read_text_no_follow(path: Path) -> str:
    """Read a regular file without following a symlink at its final component.

    job_scoped_path refuses a name that is already a symlink, but a link
    planted between that check and a plain read_text() would still be
    followed. O_NOFOLLOW makes the open itself fail (ELOOP, an OSError) on a
    link, and fstat rejects anything that is not a regular file.
    """
    fd = os.open(str(path), _CONFINED_OPEN_FLAGS)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"not a regular file: {path}")
        with os.fdopen(os.dup(fd), "rb") as fh:
            return fh.read().decode("utf-8")
    finally:
        os.close(fd)


def _load_deferral_state(job_id: str) -> dict[str, object]:
    path = _deferral_path(job_id)
    try:
        state = json.loads(_read_text_no_follow(path))
    except (OSError, ValueError):
        return {}
    # Valid JSON that is not an object (null, a list, a number) is as corrupt
    # as unparseable bytes: treat it as empty rather than letting dict() raise
    # and turn every later attempt of this job into terminal-internal-error.
    return dict(state) if isinstance(state, dict) else {}


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
    _write_job_file(_deferral_path(job_id), json.dumps(new_state))
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
    and never changes that outcome. An unsafe id never had a deferral file
    (every path builder refuses it), so there is nothing to clear.

    Deliberately not job_scoped_path: that refuses a symlink, and raising
    here would escape the handler's boundary. Unlink removes a planted
    symlink itself and never its target, so clearing one is safe and
    leaves the directory clean.
    """
    if not is_safe_job_id(job_id):
        return
    try:
        (_deferral_dir() / _job_file_name(job_id, _DEFERRAL_SUFFIX)).unlink()
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
        raw = json.loads(_read_text_no_follow(path))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        _log.warning("qwen: unreadable model digest record at %s; treating %s as unpinned", path, mask_text(model))
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
    # model is the caller's payload string, so it is masked before any log line.
    shown = mask_text(model)
    if recorded is None:
        _log.warning("qwen: no install-time digest recorded for %s; model is unpinned", shown)
        return ModelPin(running, None, "unpinned")
    if running is None:
        _log.warning("qwen: could not read the running digest for %s; pin unverified", shown)
        return ModelPin(None, None, "unverified")
    matches = _normalise_digest(running) == _normalise_digest(recorded)
    if not matches:
        _log.warning("qwen: model digest drift for %s: recorded %s, running %s", shown, recorded, running)
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


def _verdict(result: str | None) -> str:
    return "pass" if result is None else result


def _masked(value: object) -> object:
    """value with every string in it masked, dict keys included, recursively."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {_masked(k): _masked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return value


def _explain_report(
    files: list[Path], instruction: str, options: GenerationOptions, root: Path
) -> dict[str, object]:
    """Build the explain_mode report: guard results without calling the model.

    The files are read through the same descriptor-bound path a real run
    uses, and the prompt is assembled for real, so the prompt_budget
    verdict is the one the job would hit rather than an estimate.

    The report is persisted as the job's result and most of it echoes the
    payload (file paths, model, system text), so every string in it - keys
    included - is masked on the way out.
    """
    contents = _read_confined_bytes(files, root)
    per_file_bytes = {path: len(data) for path, data in contents.items()}
    # The system text shares the context window, so it counts here exactly
    # as it does in _check_prompt_budget.
    prompt_chars = len(instruction) + sum(per_file_bytes.values()) + len(options.system or "")
    prompt = _build_prompt(instruction, _decode_contents(contents))
    report: dict[str, object] = {
        "resolved_files": [str(f) for f in files],
        "per_file_bytes": per_file_bytes,
        "total_prompt_chars": prompt_chars,
        "estimated_prompt_tokens": prompt_chars // 4,
        "assembled_prompt_tokens": _estimate_request_tokens(prompt, options),
        "model": options.model,
        "options": {
            "system": options.system,
            "temperature": options.temperature,
            "max_tokens": options.max_tokens,
            "explain": options.explain,
        },
        "guard_results": {
            "confinement": "pass",
            "memory": _verdict(_check_memory_guard()),
            "disk": _verdict(_check_disk_guard()),
            "admission": _verdict(_check_admission_cap()),
            "prompt_budget": _verdict(_check_prompt_budget(prompt, options)),
        },
    }
    return {mask_text(key): _masked(value) for key, value in report.items()}


# ---------------------------------------------------------------------------
# Confined file reading: validate and read ONE descriptor.
# ---------------------------------------------------------------------------

# O_NOFOLLOW: a final-component symlink swapped in after the pre-check fails
# the open. O_NONBLOCK: a FIFO swapped in cannot hang the open (fstat then
# rejects it as not a regular file). O_CLOEXEC: no leak into subprocesses.
_CONFINED_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_MAXPATHLEN = 1024


def _fd_real_path(fd: int) -> Path | None:
    """The path the kernel reports for an open descriptor, or None when this
    platform offers no way to ask (the caller then fails closed)."""
    if sys.platform == "darwin":
        import fcntl

        try:
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(_MAXPATHLEN))
        except OSError:
            return None
        return Path(os.fsdecode(raw.split(b"\0", 1)[0]))
    if sys.platform.startswith("linux"):
        try:
            return Path(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:
            return None
    return None


def _read_open_confined(fd: int, path: Path, root: Path) -> bytes:
    """Validate THE OPENED FILE (type, size, real location), then read it."""
    denied = QwenGuardError(f"terminal-path-not-allowed: {path}")
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_size > THRESHOLDS.max_file_bytes:
        raise denied
    real = _fd_real_path(fd)
    if real is None:
        raise denied
    _check_path_policy(str(path), real, root)
    with os.fdopen(os.dup(fd), "rb") as fh:
        data = fh.read(THRESHOLDS.max_file_bytes + 1)
    if len(data) > THRESHOLDS.max_file_bytes:  # grew after the fstat
        raise denied
    return data


def _read_confined_bytes(files: list[Path], root: Path) -> dict[str, bytes]:
    """Read each resolved, pre-checked file, re-validating the descriptor itself.

    resolve_input_files checked each path before anything was opened, but a
    path can be swapped (symlink, directory, FIFO) between that check and
    an open by name. So each file is opened exactly once, and every check -
    regular file, size cap, and the allowlist/denylist containment against
    the kernel's own path for the descriptor - runs on that descriptor, and
    the bytes come from the same descriptor. Anything that fails is
    terminal-path-not-allowed; so is a platform with no way to recover a
    descriptor's path.
    """
    contents: dict[str, bytes] = {}
    for f in files:
        try:
            fd = os.open(str(f), _CONFINED_OPEN_FLAGS)
        except OSError as exc:
            raise QwenGuardError(f"terminal-path-not-allowed: {f}") from exc
        try:
            contents[str(f)] = _read_open_confined(fd, f, root)
        except OSError as exc:
            raise QwenGuardError(f"terminal-path-not-allowed: {f}") from exc
        finally:
            os.close(fd)
    return contents


def _decode_contents(contents: dict[str, bytes]) -> dict[str, str]:
    return {path: data.decode("utf-8", errors="replace") for path, data in contents.items()}


# ---------------------------------------------------------------------------
# Prompt assembly and result building.
# ---------------------------------------------------------------------------


def _estimate_prompt_tokens(prompt: str) -> int:
    """A conservative chars/4 estimate, matching explain_mode's own estimator."""
    return len(prompt) // 4


def _estimate_request_tokens(prompt: str, options: GenerationOptions) -> int:
    """Estimate every input token the request spends: the prompt AND the
    system text, which is sent to Ollama as its own field but occupies the
    same context window."""
    return _estimate_prompt_tokens(prompt + (options.system or ""))


def _check_prompt_budget(prompt: str, options: GenerationOptions) -> str | None:
    """Return "terminal-prompt-too-large" if the assembled prompt plus the

    system text exceeds the context budget (num_ctx minus the reserved
    max_tokens), else None. Fails loudly per contract.retry_map rather than
    silently truncating content the user never approved truncating.
    """
    budget = THRESHOLDS.num_ctx - options.max_tokens
    if budget <= 0 or _estimate_request_tokens(prompt, options) > budget:
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
    """The persisted success result.

    model is the only payload-derived string here, so it is masked like the
    failure strings are. Every other field is computed by the handler: the
    patch path from a validated job id, counts and durations, and the digest
    Ollama reports.
    """
    return {
        "patch_path": str(r.patch_path),
        "patch_valid": r.patch_valid,
        "files_touched": r.files_touched,
        "lines_changed": r.lines_changed,
        "model": mask_text(r.model),
        "model_digest": r.model_digest,
        "digest_matches_recorded": r.digest_matches,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "duration_ms": r.duration_ms,
        "deferral_reasons": r.deferral_reasons,
    }


_RETRYABLE_4XX = frozenset({408, 429})


_HTTP_ERROR_RE = re.compile(r"http-error-(\d{3})\b")


def _http_status(message: str) -> int | None:
    """The status code from _ollama_request's "http-error-<code>", or None."""
    match = _HTTP_ERROR_RE.match(message)
    return int(match.group(1)) if match else None


def _call_ollama_generate(host: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    """Call /api/generate and classify the failure per contract.retry_map.

    HTTP 404 -> terminal-model-not-found (a missing model stays missing on
    retry). 5xx, 408 (request timeout) and 429 (too many requests) are
    server-side or transient conditions, as is any connection-level failure
    (refused, timeout): they are re-raised as QwenTransientError so the
    caller reports a plain, retryable failure. Every other status (400, 401,
    403, ...) means the request itself was refused; re-sending the same
    request cannot fix it, so it is terminal-ollama-request-rejected rather
    than burning retry attempts.

    _ollama_request translates urlopen's errors before they reach here:
    HTTPError becomes QwenGuardError("http-error-<code>") and URLError
    becomes ConnectionError. A socket timeout during resp.read() escapes
    as a bare TimeoutError, which the OSError branch covers.
    """
    try:
        return _ollama_request(host, body, timeout)
    except QwenGuardError as exc:
        status = _http_status(str(exc))
        if status == 404:
            raise QwenGuardError("terminal-model-not-found") from exc
        if status is not None and (status >= 500 or status in _RETRYABLE_4XX):
            raise QwenTransientError(str(exc)) from exc
        raise QwenGuardError(f"terminal-ollama-request-rejected: {exc}") from exc
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
    patch_path = patch_path_for_job(job_id)
    _write_job_file(patch_path, _ensure_trailing_newline(diff))
    return patch_path


DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096
# Ollama accepts any float, but above 2 sampling degenerates into noise that
# will never parse as a diff; below 0 is meaningless.
MAX_TEMPERATURE = 2.0


def _invalid_option(message: str) -> QwenGuardError:
    return QwenGuardError(f"terminal-invalid-payload: {message}")


def _finite_number(value: object) -> float | None:
    """value as a float when it is a finite JSON number, else None.

    bool is refused although Python counts True as an int, and so are NaN
    and the infinities, which compare false against every bound.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _option_max_tokens(raw: object) -> int:
    """max_tokens is Ollama's num_predict, where -1 means unlimited, so the
    range is enforced: at least one token, and less than the whole context."""
    if raw is None:
        return DEFAULT_MAX_TOKENS
    upper = THRESHOLDS.num_ctx - 1
    if not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= upper:
        raise _invalid_option(f"max_tokens must be an int in [1, {upper}]")
    return raw


def _option_temperature(raw: object) -> float:
    if raw is None:
        return DEFAULT_TEMPERATURE
    value = _finite_number(raw)
    if value is None or not 0 <= value <= MAX_TEMPERATURE:
        raise _invalid_option(f"temperature must be a finite number in [0, {MAX_TEMPERATURE}]")
    return value


def _option_str(raw: object, name: str) -> str | None:
    """An optional string option; None when absent or empty."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _invalid_option(f"{name} must be a str")
    return raw or None


def _option_explain(raw: object) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise _invalid_option("explain must be a bool")
    return raw


def _resolve_payload_options(payload: dict[str, object]) -> GenerationOptions:
    """Validate and resolve the optional payload keys. Raises QwenGuardError.

    Runs before any file is touched and before the prompt-budget guard.
    Every key is type-checked rather than coerced: a coercion let
    max_tokens -1 (Ollama's "unlimited") or a NaN temperature through, and
    turned a non-string system prompt into a silent no-op.
    """
    return GenerationOptions(
        model=_option_str(payload.get("model"), "model") or DEFAULT_MODEL_TAG,
        system=_option_str(payload.get("system"), "system"),
        temperature=_option_temperature(payload.get("temperature")),
        max_tokens=_option_max_tokens(payload.get("max_tokens")),
        explain=_option_explain(payload.get("explain")),
    )


def _resolve_timeout(payload: dict[str, object]) -> float:
    """payload["timeout"] is only injected by job_runtime, and only for a
    positive resolved timeout_sec; anything else there was put in the payload
    by hand and is rejected like any other invalid option. Raises QwenGuardError.
    """
    raw = payload.get("timeout")
    if raw is None:
        return THRESHOLDS.ollama_request_timeout_sec
    value = _finite_number(raw)
    if value is None or value <= 0:
        raise _invalid_option("timeout must be a finite number > 0")
    return value


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
    holder = _acquire_model_lock(job_id)
    if not holder:
        return "deferred-qwen-busy"
    try:
        return _generate_and_validate_patch(host, prompt, options, timeout)
    except QwenGuardError as exc:
        return str(exc)
    except QwenTransientError as exc:
        return f"{TRANSIENT_OUTCOME_PREFIX}: {exc}"
    finally:
        _release_model_lock(job_id, holder)


@dataclass
class _JobRun:
    """Per-job telemetry facts, filled in as the job progresses.

    handle_qwen_patch emits exactly one span + metrics from this at its
    single exit, whatever the outcome. A guard exit leaves generation_ns and
    the token counts unset, so its span covers the handler's own run and no
    token metrics are sent.
    """

    identity: JobIdentity
    start_ns: int
    generation_ns: tuple[int, int] | None = None
    patch_valid: bool | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    pin: ModelPin | None = None
    explain: bool = False


@dataclass(frozen=True)
class _PreparedJob:
    """A validated payload: confined files plus the resolved options."""

    files: list[Path]
    instruction: str
    options: GenerationOptions
    host: str
    root: Path


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


def _telemetry_event(run: _JobRun, outcome: str, end_ns: int) -> _TelemetryEvent:
    """The model call's own window when there was one, else the handler's run."""
    start_ns, stop_ns = run.generation_ns if run.generation_ns is not None else (run.start_ns, end_ns)
    return _TelemetryEvent(
        run.identity, outcome, run.patch_valid, start_ns, stop_ns, run.prompt_tokens, run.completion_tokens, run.pin
    )


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


def _export_event(event: _TelemetryEvent, attrs: dict[str, object]) -> None:
    # export_job_span/export_job_metrics are imported at module scope (not
    # locally) specifically so mock.patch("worker.qwen.export_job_span", ...)
    # — patch where the name is used, per house convention — actually
    # intercepts these calls. Each call sits in its own try/except so a
    # failure in one can never skip the other: span and metrics export are
    # independent best-effort paths.
    try:
        export_job_span(attrs, event.start_ns, event.end_ns)
    except Exception:  # nosec B110 - contract.telemetry.failure_is_nonfatal: export must never affect job outcome, independent of export_job_span's own internal guard
        _log.debug("qwen: span telemetry export raised (non-fatal)", exc_info=True)
    try:
        duration_ms = (event.end_ns - event.start_ns) / 1_000_000
        export_job_metrics(attrs, duration_ms, event.prompt_tokens, event.completion_tokens)
    except Exception:  # nosec B110 - contract.telemetry.failure_is_nonfatal: export must never affect job outcome, independent of export_job_metrics's own internal guard
        _log.debug("qwen: metrics telemetry export raised (non-fatal)", exc_info=True)


def _emit_telemetry(event: _TelemetryEvent) -> None:
    """Hand the span and metrics to one background export thread and return.

    The attributes are built (and masked) here, on the job's thread; only
    the network calls move off it, so a slow or blackholed collector never
    delays the job.
    """
    try:
        attrs = _telemetry_attrs(event)
        export_in_background(lambda: _export_event(event, attrs))
    except Exception:  # nosec B110 - contract.telemetry.failure_is_nonfatal: even failing to schedule the export must not affect the job
        _log.debug("qwen: could not schedule telemetry export (non-fatal)", exc_info=True)


def _deferral_outcome(job_id: str, reason: str, outcome: str) -> str:
    """Record one deferral; return outcome, or the terminal limit verdict once reached."""
    count = _record_deferral(job_id, reason)
    return _deferral_limit_verdict(job_id, count) or outcome


def _handle_string_outcome(job_id: str, outcome: str) -> tuple[bool, object]:
    """Turn a deferred/terminal string outcome from _run_with_lock into a result tuple."""
    if outcome == "deferred-qwen-busy":
        return (False, _deferral_outcome(job_id, "qwen-busy", outcome))
    return (False, outcome)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _finalize_success(run: _JobRun, host: str, diff: str, response: dict[str, object]) -> tuple[bool, object]:
    """Write the patch, compute stats/pinning, record telemetry facts, and build the success result."""
    patch_path = _write_patch_file(run.identity.job_id, diff)
    paths_touched, lines_changed = diff_stats(diff)
    run.pin = _check_model_pin(host, run.identity.model)
    run.prompt_tokens = _int_or_none(response.get("prompt_eval_count"))
    run.completion_tokens = _int_or_none(response.get("eval_count"))
    run.patch_valid = True
    start_ns, end_ns = run.generation_ns or (run.start_ns, time.time_ns())

    result = _build_result(
        GenerationResult(
            patch_path=patch_path,
            patch_valid=True,
            files_touched=len(paths_touched),
            lines_changed=lines_changed,
            model=run.identity.model,
            model_digest=run.pin.running_digest,
            digest_matches=run.pin.matches_recorded,
            prompt_tokens=run.prompt_tokens,
            completion_tokens=run.completion_tokens,
            duration_ms=(end_ns - start_ns) // 1_000_000,
        )
    )
    return (True, result)


def _run_generation(run: _JobRun, prepared: _PreparedJob, timeout: float) -> tuple[bool, object]:
    """Guarded model call through result building. Assumes explain/admission/memory already checked."""
    contents = _read_confined_bytes(prepared.files, prepared.root)
    prompt = _build_prompt(prepared.instruction, _decode_contents(contents))

    budget_verdict = _check_prompt_budget(prompt, prepared.options)
    if budget_verdict is not None:
        return (False, budget_verdict)

    job_id = run.identity.job_id
    start_ns = time.time_ns()
    outcome = _run_with_lock(job_id, prepared.host, prompt, prepared.options, timeout)
    run.generation_ns = (start_ns, time.time_ns())

    if isinstance(outcome, str):
        return _handle_string_outcome(job_id, outcome)

    diff, response = outcome
    disk_verdict = _check_disk_guard()
    if disk_verdict is not None:
        return (False, _deferral_outcome(job_id, "low-disk", disk_verdict))

    return _finalize_success(run, prepared.host, diff, response)


def _run_guarded(payload: dict[str, object], run: _JobRun) -> tuple[bool, object]:
    """Guards + generation, run inside the outer exception boundary."""
    job_id = run.identity.job_id
    if not is_safe_job_id(job_id):
        # Before anything else: every later step may build a path from it.
        return (False, INVALID_JOB_ID_OUTCOME)
    files, instruction = _validate_payload(payload)
    # Every option is validated before confinement touches the disk.
    options = _resolve_payload_options(payload)
    timeout = _resolve_timeout(payload)
    root = _repo_root().resolve()
    prepared = _PreparedJob(
        files=resolve_input_files(files, root),
        instruction=instruction,
        options=options,
        host=os.environ.get("QWEN_OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        root=root,
    )

    if prepared.options.explain:
        run.explain = True
        return (True, _explain_report(prepared.files, instruction, prepared.options, root))

    admission_verdict = _check_admission_cap()
    if admission_verdict is not None:
        return (False, admission_verdict)

    memory_verdict = _check_memory_guard()
    if memory_verdict is not None:
        return (False, _deferral_outcome(job_id, "low-memory", memory_verdict))

    return _run_generation(run, prepared, timeout)


def _job_identity(job: dict[str, object], payload: dict[str, object]) -> JobIdentity:
    """Identity for telemetry, derived without any step that can raise."""
    try:
        attempt = _as_int(job.get("attempts"), 0)
    except (TypeError, ValueError):
        attempt = 0
    return JobIdentity(
        job_id=str(job.get("id") or ""),
        model=str(payload.get("model") or DEFAULT_MODEL_TAG),
        attempt=attempt,
    )


def handle_qwen_patch(job: dict[str, object]) -> tuple[bool, object]:  # noqa - registered in handlers.REGISTRY
    """qwen_patch handler.

    job is the full job record; job["payload"] carries files, instruction,
    and optional model/system/temperature/max_tokens/explain/timeout keys.
    Never raises: the whole body runs inside one outer exception boundary
    that returns a masked, content-free string rather than letting a
    traceback (which could carry file content raised during prompt assembly)
    reach job_runtime's unmasked error path.

    The boundary is also the single exit every outcome passes through, so
    three rules are applied here once rather than at each return site: every
    failure string is masked (job_runtime writes it to last_error verbatim);
    the deferral side-channel file is deleted on success and on every
    terminal-* exit (contract.deferral_bound.cleanup); and exactly one span
    plus metrics are emitted for every outcome - guard exits, deferrals and
    internal errors included. The one exception is a successful explain-mode
    run, which is a dry-run report rather than a job outcome.
    """
    raw_payload = job.get("payload")
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    run = _JobRun(identity=_job_identity(job, payload), start_ns=time.time_ns())
    try:
        ok, out = _run_guarded(payload, run)
    except QwenGuardError as exc:
        ok, out = False, str(exc)
    except Exception as exc:  # nosec B110 - exception boundary: convert to a content-free terminal string per contract.redaction.exception_boundary
        ok, out = False, f"terminal-internal-error: {type(exc).__name__}"
    if not ok:
        out = mask_text(str(out))
    if ok or str(out).startswith("terminal-"):
        _clear_deferral_state(run.identity.job_id)
    if not (ok and run.explain):
        _emit_telemetry(_telemetry_event(run, "success" if ok else str(out), time.time_ns()))
    return ok, out
