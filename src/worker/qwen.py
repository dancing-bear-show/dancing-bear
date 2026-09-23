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


def handle_qwen_patch(job: dict[str, object]) -> tuple[bool, object]:  # noqa - registered in handlers.REGISTRY
    """qwen_patch handler.

    job is the full job record; job["payload"] carries files, instruction,
    and optional model/system/temperature/max_tokens/explain/timeout keys.
    Never raises: every branch below is reached through the outer exception
    boundary added in a later checkpoint.
    """
    payload = dict(job.get("payload") or {})
    try:
        files, _instruction = _validate_payload(payload)
        resolve_input_files(files, _repo_root())
    except QwenGuardError as exc:
        return (False, str(exc))
    return (False, "terminal-not-implemented")
