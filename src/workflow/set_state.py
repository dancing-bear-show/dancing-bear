"""Hand-seeded stage results for ``workflow set-state`` and ``seed-pr-lifecycle``.

Both commands write ``{workspace}/stages/{NNN}-{stage_name}.json`` markers for
stages that finished outside the orchestrator (for example a PR shipped by a
hand-dispatched agent), so ``workflow resume`` and the orchestrator's resume
path stop treating them as pending.

Markers go through :func:`workflow.persistence.write_stage_result` and the real
:class:`StageResult` dataclass, never hand-rolled JSON.  The new marker gets
``stage_index = max(existing) + 1`` by default, so it outranks any earlier
marker for the same stage: ``list_stage_results`` sorts by index and
``read_stage_result`` takes the highest-numbered file.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.date_utils import iso_now
from workflow.models import StageResult, StageStatus
from workflow.persistence import list_stage_results, write_stage_result

# A stage name is embedded in a filename under stages/, so it is held to the
# character set every shipped workflow already uses.  This rejects "/", "..",
# and anything else that could move the marker out of stages/.
_STAGE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

SEEDED_BY = "workflow-set-state"

#: Fragment whose stages ``seed-pr-lifecycle`` backfills by default.
DEFAULT_PR_FRAGMENT = "workflows/shared/pr-open-and-wait-ci.yaml"

# The fragment stage that opens the PR carries the PR number and URL, matching
# what the real stage records in validation/pr.json.
_OPEN_PR_STAGE = "open-pr"


class SeedError(ValueError):
    """A set-state / seed request was rejected before anything was written."""


@dataclass(frozen=True)
class SeededStage:
    """One marker written by set-state or seed-pr-lifecycle."""

    stage_name: str
    stage_index: int
    status: StageStatus
    path: Path


def check_stage_name(name: str, known_stages: Sequence[str] = ()) -> None:
    """Raise SeedError unless *name* is filename-safe and, if known, in the plan.

    *known_stages* is the run's planned stage list (empty when the workspace
    has no plan).  A marker for a stage outside it would be ignored by
    ``resume``, so a typo is rejected instead of silently recorded.
    """
    if not _STAGE_NAME_RE.fullmatch(name):
        raise SeedError(
            f"invalid stage name {name!r}: must match {_STAGE_NAME_RE.pattern}"
        )
    if known_stages and name not in known_stages:
        raise SeedError(f"stage {name!r} is not in this run's plan")


def next_stage_index(workspace_dir: str | Path) -> int:
    """Return max(stage_index) + 1 over existing markers, or 0 when none exist."""
    existing = list_stage_results(workspace_dir)
    return max((r.stage_index for r in existing), default=-1) + 1


def _seeded_result(
    stage_name: str,
    stage_index: int,
    status: StageStatus,
    data: dict[str, Any],
    note: str | None,
) -> StageResult:
    """Build a zero-duration StageResult carrying seeded_by/seeded_at metadata."""
    now = iso_now()
    metadata: dict[str, Any] = {"seeded_by": SEEDED_BY, "seeded_at": now}
    if note:
        metadata["note"] = note
    return StageResult(
        stage_name=stage_name,
        stage_index=stage_index,
        status=status,
        started_at=now,
        finished_at=now,
        duration_ms=0,
        data=data,
        metadata=metadata,
    )


@dataclass(frozen=True)
class SetStateRequest:
    """Inputs for :func:`set_state` beyond the workspace and stage name."""

    status: StageStatus = StageStatus.success
    data: dict[str, Any] | None = None
    note: str | None = None
    stage_index: int | None = None


def set_state(
    workspace_dir: str | Path,
    stage_name: str,
    request: SetStateRequest,
    known_stages: Sequence[str] = (),
) -> SeededStage:
    """Write one hand-seeded marker for *stage_name* and return it."""
    check_stage_name(stage_name, known_stages)
    if request.stage_index is not None and request.stage_index < 0:
        raise SeedError(f"stage index must be >= 0, got {request.stage_index}")
    index = (
        request.stage_index
        if request.stage_index is not None
        else next_stage_index(workspace_dir)
    )
    result = _seeded_result(
        stage_name, index, request.status, dict(request.data or {}), request.note
    )
    path = write_stage_result(workspace_dir, result)
    return SeededStage(stage_name, index, request.status, path)


@dataclass(frozen=True)
class PrSeed:
    """The PR a lifecycle group is being backfilled for."""

    pr_number: int
    url: str | None = None
    note: str | None = None


def seed_pr_lifecycle(
    workspace_dir: str | Path,
    prefix: str,
    suffixes: Sequence[str],
    pr: PrSeed,
    known_stages: Sequence[str] = (),
) -> list[SeededStage]:
    """Mark every ``{prefix}-{suffix}`` stage success, in *suffixes* order.

    Every name is validated before the first write, so a bad prefix or a
    stage missing from the plan leaves the workspace untouched.  Each payload
    carries ``{"pr": N}``; the open-pr stage also gets ``pr_number`` and, when
    given, ``url``.
    """
    if pr.pr_number <= 0:
        raise SeedError(f"PR number must be positive, got {pr.pr_number}")
    if not suffixes:
        raise SeedError("fragment defines no stages to seed")
    names = [f"{prefix}-{suffix}" for suffix in suffixes]
    for name in names:
        check_stage_name(name, known_stages)

    start = next_stage_index(workspace_dir)
    seeded: list[SeededStage] = []
    for offset, (suffix, name) in enumerate(zip(suffixes, names, strict=True)):
        data: dict[str, Any] = {"pr": pr.pr_number}
        if suffix == _OPEN_PR_STAGE:
            data["pr_number"] = pr.pr_number
            if pr.url:
                data["url"] = pr.url
        result = _seeded_result(name, start + offset, StageStatus.success, data, pr.note)
        path = write_stage_result(workspace_dir, result)
        seeded.append(SeededStage(name, start + offset, StageStatus.success, path))
    return seeded
