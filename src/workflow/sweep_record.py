"""Evidence that the pre-Copilot concern swarm ran on a commit.

A record is one JSON file per commit, stored under the repository's git common
directory so every worktree of the checkout sees the same set::

    <git common dir>/dancing-bear/concern-sweeps/<head_sha>.json

It lives inside ``.git``, so it is never tracked, never pushed and never shows
up in ``git status``. The PR-create hook (``require-concern-sweep.sh``) reads
the same path directly, without importing this module; keep the location and
field names in step with it.

Directories are created with mode 0o700 (and the record file inherits the
0o600 of ``tempfile.mkstemp``). A record is a permission slip: the hook lets a
PR open when one exists. Leaving the directory group- or world-writable, as a
permissive umask would, lets another local account plant a record for any
commit, so the tighter mode is deliberate rather than the repo default.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - fixed git argv lists, never a shell
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RECORD_SUBDIR = ("dancing-bear", "concern-sweeps")
REQUIRED_GUIDE = "collateral-damage.md"
INDEX_NAME = "concern-sweep-index.json"
# Both swarm paths write the same file: the small path's review-consolidated
# stage and the large path's consolidate stage each list consolidated.json in
# writes_to (workflows/shared/code-review-swarm.yaml). Either satisfies this.
REVIEW_OUTPUTS: dict[str, str] = {
    "review-consolidated": "consolidated.json",
    "consolidate": "consolidated.json",
}
MODE_SWEPT = "swept"
MODE_WAIVED = "waived"
MODES = (MODE_SWEPT, MODE_WAIVED)

_SHA_RE = re.compile(r"[0-9a-f]{40}")
# Variables that would point git at a different repository than the checkout.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


class SweepRecordError(Exception):
    """A request the sweep-record CLI refuses. The message says why."""


@dataclass
class SweepRecord:
    head_sha: str
    mode: str
    guides: list[str] = field(default_factory=list)
    workspace: str | None = None
    reason: str | None = None
    recorded_at: str = ""

    def to_dict(self) -> dict[str, object]:
        """The on-disk shape; require-concern-sweep's helper reads head_sha and mode."""
        return {
            "head_sha": self.head_sha,
            "mode": self.mode,
            "guides": list(self.guides),
            "workspace": self.workspace,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
        }


def validate_sha(head: str) -> str:
    """Return ``head`` if it is a full 40-char lowercase hex OID, else raise."""
    if not isinstance(head, str) or not _SHA_RE.fullmatch(head):
        raise SweepRecordError("--head must be a full 40-character lowercase hex commit id")
    return head


def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}
    proc = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SweepRecordError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout_root(start: Path) -> Path:
    """The top level of the checkout containing ``start``."""
    return Path(_git(start, "rev-parse", "--show-toplevel"))


def records_dir(repo: Path) -> Path:
    """``<git common dir>/dancing-bear/concern-sweeps`` for the checkout at ``repo``."""
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    return common.resolve().joinpath(*RECORD_SUBDIR)


def record_path(repo: Path, head: str) -> Path:
    return records_dir(repo) / f"{validate_sha(head)}.json"


def _require_head_is_checkout_head(repo: Path, head: str) -> None:
    actual = _git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    if actual != head:
        raise SweepRecordError(
            f"--head {head} is not this checkout's HEAD ({actual}); "
            "sweep the commit you are about to open"
        )


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SweepRecordError(f"{label} not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise SweepRecordError(f"{label} is unreadable or not JSON: {path} ({exc})") from None


def index_guides(workspace: Path) -> list[str]:
    """The ``data.guide`` values of ``outputs/concern-sweep-index.json``, in order."""
    path = workspace / "outputs" / INDEX_NAME
    data = _load_json(path, INDEX_NAME)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SweepRecordError(f"{INDEX_NAME} has no 'items' list: {path}")
    guides: list[str] = []
    for item in items:
        entry = item.get("data") if isinstance(item, dict) else None
        guide = entry.get("guide") if isinstance(entry, dict) else None
        if isinstance(guide, str) and guide not in guides:
            guides.append(guide)
    return guides


def _require_review_output(workspace: Path) -> None:
    outputs = workspace / "outputs"
    names = sorted(set(REVIEW_OUTPUTS.values()))
    for name in names:
        path = outputs / name
        if path.is_file():
            _load_json(path, name)
            return
    raise SweepRecordError(
        "no swarm review output in the workspace: expected outputs/"
        + " or outputs/".join(names)
        + " (review-consolidated or consolidate stage)"
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mkdir_private(path: Path) -> None:
    """Create ``path`` and any missing parents under the common dir as 0o700."""
    missing: list[Path] = []
    cur = path
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)


def _write_atomic(path: Path, record: SweepRecord) -> None:
    _mkdir_private(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_swept(repo: Path, head: str, workspace: Path) -> tuple[Path, SweepRecord]:
    """Validate a swarm workspace for ``head`` and record it as swept."""
    validate_sha(head)
    root = checkout_root(repo)
    _require_head_is_checkout_head(root, head)
    ws = workspace.expanduser().resolve()
    if not ws.is_dir():
        raise SweepRecordError(f"--workspace is not a directory: {ws}")
    guides = index_guides(ws)
    if REQUIRED_GUIDE not in guides:
        raise SweepRecordError(
            f"{INDEX_NAME} does not include {REQUIRED_GUIDE}; the swarm did not sweep it"
        )
    _require_review_output(ws)
    record = SweepRecord(
        head_sha=head, mode=MODE_SWEPT, guides=guides, workspace=str(ws),
        reason=None, recorded_at=_now(),
    )
    path = record_path(root, head)
    _write_atomic(path, record)
    return path, record


def write_waived(repo: Path, head: str, reason: str) -> tuple[Path, SweepRecord]:
    """Record that the sweep was deliberately skipped for ``head``."""
    validate_sha(head)
    if not reason or not reason.strip():
        raise SweepRecordError("--reason must be non-empty")
    root = checkout_root(repo)
    record = SweepRecord(
        head_sha=head, mode=MODE_WAIVED, guides=[], workspace=None,
        reason=reason.strip(), recorded_at=_now(),
    )
    path = record_path(root, head)
    _write_atomic(path, record)
    return path, record


def read_record(repo: Path, head: str) -> SweepRecord | None:
    """The record for ``head``, or None if there is none or it is malformed."""
    path = record_path(checkout_root(repo), head)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("head_sha") != head or data.get("mode") not in MODES:
        return None
    guides = data.get("guides")
    return SweepRecord(
        head_sha=head,
        mode=str(data["mode"]),
        guides=[g for g in guides if isinstance(g, str)] if isinstance(guides, list) else [],
        workspace=data.get("workspace") if isinstance(data.get("workspace"), str) else None,
        reason=data.get("reason") if isinstance(data.get("reason"), str) else None,
        recorded_at=str(data.get("recorded_at", "")),
    )
