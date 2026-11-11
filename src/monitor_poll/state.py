"""Poll state files: one JSON file per poll, used by ``status`` and ``cancel``.

State tracking is auxiliary. A directory that cannot be created or written
(restricted HOME, sandbox) must never stop a poll, so write failures degrade to
a stderr warning instead of an exception.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.date_utils import iso_now
from core.fileutil import atomic_write_json, safe_load_json
from core.paths import output_dir

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

# Finished state files older than this are pruned on ``status`` reads.
STALE_FILE_AGE_SECONDS = 24 * 60 * 60

_DOMAIN = "monitor-poll"


def state_dir() -> Path:
    """Return the state directory (not created). Honors ``DANCING_BEAR_DATA_HOME``."""
    return output_dir(_DOMAIN)


@dataclass
class PollState:
    """Persisted record of one poll."""

    poll_id: str
    pid: int
    condition: str
    args: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    status: str = STATUS_RUNNING

    @classmethod
    def from_dict(cls, data: object) -> PollState | None:
        """Build from untrusted JSON; None when it is not a usable record."""
        if not isinstance(data, dict):
            return None
        raw_args = data.get("args")
        return cls(
            poll_id=str(data.get("poll_id") or ""),
            pid=coerce_pid(data.get("pid")),
            condition=str(data.get("condition") or ""),
            args=raw_args if isinstance(raw_args, dict) else {},
            started_at=str(data.get("started_at") or ""),
            status=str(data.get("status") or "unknown"),
        )


def coerce_pid(raw: object) -> int:
    """Best-effort int for a state file's ``pid``; 0 means "no usable pid"."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return 0
    try:
        return int(raw)
    except (ValueError, OverflowError):
        return 0


def state_path(poll_id: str, root: Path | None = None) -> Path:
    return (root or state_dir()) / f"{poll_id}.json"


def write_state(state: PollState, root: Path | None = None) -> None:
    """Atomically persist ``state``; warn on stderr instead of raising."""
    path = state_path(state.poll_id, root)
    try:
        atomic_write_json(path, asdict(state))
    except OSError as exc:
        print(f"warning: cannot write poll state {path}: {exc}", file=sys.stderr)


@contextmanager
def tracked_poll(
    condition: str, args: dict[str, Any], root: Path | None = None
) -> Iterator[PollState]:
    """Persist a state file for the lifetime of a poll.

    The caller sets ``state.status`` to a terminal value before leaving the
    block. A caller that forgets is recorded as ``error`` (over-reporting a
    failure beats reporting an unset outcome as success); an exception, or an
    interrupt, is recorded as ``error`` too. The file is rewritten on exit.
    """
    state = PollState(
        poll_id=uuid.uuid4().hex,
        pid=os.getpid(),
        condition=condition,
        args=args,
        started_at=iso_now(),
    )
    write_state(state, root)
    try:
        yield state
        if state.status == STATUS_RUNNING:
            state.status = STATUS_ERROR
    except BaseException:
        state.status = STATUS_ERROR
        raise
    finally:
        write_state(state, root)


def is_pid_alive(pid: int) -> bool:
    """True when ``pid`` is a live process. EPERM counts as alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def prune_stale(root: Path, now: float | None = None) -> None:
    """Delete state files not modified within ``STALE_FILE_AGE_SECONDS``."""
    cutoff = (time.time() if now is None else now) - STALE_FILE_AGE_SECONDS
    for path in root.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:  # nosec B110 - pruning is best-effort; a racing delete is fine
            pass


def load_states(root: Path) -> list[PollState]:
    """Load every readable state file, oldest first; skip unusable ones."""
    states: list[PollState] = []
    for path in sorted(root.glob("*.json")):
        state = PollState.from_dict(safe_load_json(path))
        if state is not None:
            states.append(state)
    return sorted(states, key=lambda s: (s.started_at, s.poll_id))


def find_state(
    states: list[PollState], poll_id: str | None, pid: int | None
) -> PollState | None:
    """First state matching ``poll_id`` or ``pid``; None when nothing matches."""
    for state in states:
        if poll_id and state.poll_id == poll_id:
            return state
        if pid is not None and pid > 0 and state.pid == pid:
            return state
    return None


def skip_signal_reason(state: PollState) -> str | None:
    """Why ``state`` must NOT be signalled, or None when signalling is safe.

    A finished poll's pid may have been reused by an unrelated process, and
    ``os.kill(0, ...)`` signals a whole process group, so both are refused.
    """
    if state.pid <= 0:
        return "no pid recorded"
    if state.status != STATUS_RUNNING:
        return f"poll already finished (status={state.status})"
    if not is_pid_alive(state.pid):
        return "process already finished or not found"
    return None


def send_sigterm(pid: int) -> str | None:
    """SIGTERM ``pid``; return an error message on failure, None on success."""
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return f"failed to signal pid {pid}: {exc}"
    return None
