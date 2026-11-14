"""Fleet ledger: track one workflow across many items, in resumable batches.

A fleet is one workflow YAML fanned over a list of items (repos, profiles,
domains...).  The ledger records each item's status and run workspace, so a
long fleet survives interruption and is resumed batch by batch.

The ledger never executes stages itself.  ``fleet run`` creates a workspace per
item and marks it ``running``; the executor (the ``/workflow`` skill) runs it
and reports back with ``fleet mark``.  A failed item that is picked up again
keeps its workspace, so the retry resumes; ``fleet reset`` clears it for a
fresh start.  Shelling out to ``workflow run --execute``
was deliberately not ported: for agent stages without generate/template outputs
it stubs outputs and records success, which across a fleet would mark every
item done with no work performed.

Ledger: ``<data-home>/workflow-fleet/<slug>/ledger.json``, guarded by a
companion ``.lock`` file (``fcntl.flock``) so concurrent ``mark`` calls from
parallel agents do not lose updates.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from core.date_utils import iso_now
from core.fileutil import atomic_write_json
from core.paths import output_dir

LEDGER_DOMAIN = "workflow-fleet"

_SLUG_UNSAFE = re.compile(r"[^a-z0-9-]+")


class ItemStatus(StrEnum):
    """Per-item fleet status (coarser than a stage's StageStatus)."""

    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


# Statuses picked up by the next batch: a failed item is retried.
RETRYABLE_STATUSES = frozenset({ItemStatus.pending, ItemStatus.failed})
MARK_STATUSES = (ItemStatus.running, ItemStatus.done, ItemStatus.failed, ItemStatus.skipped)


class FleetError(ValueError):
    """A fleet request was rejected (bad source, missing ledger, bad status)."""


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _status(value: object) -> ItemStatus:
    """Decode a ledger status, treating an unknown value as pending."""
    try:
        return ItemStatus(str(value))
    except ValueError:
        return ItemStatus.pending


@dataclass
class ItemRecord:
    """Ledger entry for one fleet item."""

    status: ItemStatus = ItemStatus.pending
    workspace: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "workspace": self.workspace,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ItemRecord:
        return cls(
            status=_status(data.get("status")),
            workspace=_opt_str(data.get("workspace")),
            started_at=_opt_str(data.get("started_at")),
            completed_at=_opt_str(data.get("completed_at")),
            error=_opt_str(data.get("error")),
        )


@dataclass
class Ledger:
    """Fleet ledger, persisted as JSON."""

    workflow: str  # slug; also the ledger directory name
    workflow_path: str
    fan_over: str
    created_at: str
    last_updated: str
    items: dict[str, ItemRecord] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "workflow": self.workflow,
            "workflow_path": self.workflow_path,
            "fan_over": self.fan_over,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "items": {k: v.as_dict() for k, v in self.items.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Ledger:
        raw_items = data.get("items")
        items = raw_items if isinstance(raw_items, dict) else {}
        return cls(
            workflow=str(data.get("workflow") or ""),
            workflow_path=str(data.get("workflow_path") or ""),
            fan_over=str(data.get("fan_over") or ""),
            created_at=str(data.get("created_at") or ""),
            last_updated=str(data.get("last_updated") or ""),
            items={
                str(k): ItemRecord.from_dict(v if isinstance(v, dict) else {})
                for k, v in items.items()
            },
        )

    def counts(self) -> Counter[ItemStatus]:
        return Counter(rec.status for rec in self.items.values())


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def workflow_slug(name: str) -> str:
    """Filesystem-safe ``[a-z0-9-]+`` slug for a workflow name (the ledger dir)."""
    slug = _SLUG_UNSAFE.sub("-", name.lower()).strip("-")
    if not slug:
        raise FleetError(f"workflow name {name!r} produces an empty ledger slug")
    return slug


def ledger_path(slug: str) -> Path:
    return output_dir(LEDGER_DOMAIN) / slug / "ledger.json"


@contextmanager
def _locked(path: Path, *, shared: bool = False) -> Iterator[None]:
    """Hold a flock on ``<ledger>.lock``; a no-op where fcntl is unavailable."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX platform
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read(path: Path) -> Ledger | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise FleetError(f"cannot read fleet ledger {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise FleetError(f"fleet ledger {path} is not a JSON object")
    return Ledger.from_dict(data)


def load_ledger(slug: str) -> Ledger | None:
    """Load a ledger, or None when the fleet has never been started.

    A missing ledger returns before locking, so a read (or ``run --dry-run``)
    never creates the ledger directory or lock file.
    """
    path = ledger_path(slug)
    if not path.exists():
        return None
    with _locked(path, shared=True):
        return _read(path)


def require_ledger(slug: str) -> Ledger:
    ledger = load_ledger(slug)
    if ledger is None:
        raise FleetError(f"no fleet ledger for workflow {slug!r}; start one with 'fleet run'")
    return ledger


def save_ledger(ledger: Ledger) -> None:
    path = ledger_path(ledger.workflow)
    ledger.last_updated = iso_now()
    with _locked(path):
        atomic_write_json(path, ledger.as_dict())


def update_item(slug: str, item: str, **fields: object) -> ItemRecord:
    """Read-modify-write one item under the exclusive lock; return the new record."""
    path = ledger_path(slug)
    with _locked(path):
        ledger = _read(path)
        if ledger is None:
            raise FleetError(f"no fleet ledger for workflow {slug!r}; start one with 'fleet run'")
        if item not in ledger.items:
            raise FleetError(f"item {item!r} is not in the {slug!r} fleet ledger")
        merged = {**ledger.items[item].as_dict(), **fields}
        record = ItemRecord.from_dict(merged)
        ledger.items[item] = record
        ledger.last_updated = iso_now()
        atomic_write_json(path, ledger.as_dict())
    return record


# ---------------------------------------------------------------------------
# Items and batches
# ---------------------------------------------------------------------------


def enumerate_items(source: str) -> list[str]:
    """Items from ``items:a,b,c`` or ``file:<path>`` (one per line, # comments).

    Order is preserved and duplicates dropped.
    """
    if source.startswith("items:"):
        raw: Iterable[str] = source[len("items:"):].split(",")
    elif source.startswith("file:"):
        path = Path(source[len("file:"):]).expanduser()
        try:
            raw = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise FleetError(f"cannot read item file {path}: {exc}") from exc
        raw = (ln for ln in raw if not ln.lstrip().startswith("#"))
    else:
        raise FleetError(f"unknown --fan-over source {source!r}; use items:a,b or file:<path>")
    items = list(dict.fromkeys(x.strip() for x in raw if x.strip()))
    if not items:
        raise FleetError(f"--fan-over {source!r} yielded no items")
    return items


def substitute_item(templates: Iterable[str], item: str) -> list[str]:
    """Replace ``{item}`` in each ``key=value`` template."""
    return [t.replace("{item}", item) for t in templates]


def merge_items(ledger: Ledger, items: Iterable[str]) -> int:
    """Add unseen items as pending (existing keep their status); return count added."""
    added = 0
    for item in items:
        if item not in ledger.items:
            ledger.items[item] = ItemRecord()
            added += 1
    return added


def reset_items(ledger: Ledger, names: Iterable[str]) -> list[str]:
    """Return the named items that exist to a fresh pending record."""
    reset = [n for n in dict.fromkeys(names) if n in ledger.items]
    for name in reset:
        ledger.items[name] = ItemRecord()
    return reset


def select_batch(ledger: Ledger, batch_size: int) -> list[str]:
    """Next pending/failed items in sorted order (all of them when batch_size is 0)."""
    eligible = sorted(n for n, r in ledger.items.items() if r.status in RETRYABLE_STATUSES)
    return eligible if batch_size == 0 else eligible[:batch_size]


def mark_fields(status: ItemStatus, workspace: str | None, error: str | None) -> dict[str, object]:
    """Ledger fields for a ``mark``: running clears completion; terminal stamps it."""
    if status not in MARK_STATUSES:
        raise FleetError(f"cannot mark an item {status.value!r}; use 'fleet reset' for pending")
    fields: dict[str, object] = {"status": status.value, "error": error}
    if status == ItemStatus.running:
        fields.update(started_at=iso_now(), completed_at=None)
    else:
        fields["completed_at"] = iso_now()
    if workspace is not None:
        fields["workspace"] = workspace
    return fields
