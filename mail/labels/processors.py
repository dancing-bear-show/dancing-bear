"""Processors for labels pipelines."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.pipeline import Processor, ResultEnvelope

from .consumers import LabelsPlanPayload, LabelsSyncPayload, LabelsExportPayload


@dataclass
class LabelChange:
    name: str
    changes: dict[str, dict[str, str]]
    spec: dict


@dataclass
class LabelsPlanResult:
    to_create: list[dict]
    to_update: list[LabelChange]
    to_delete: list[str]
    show_delete: bool


class LabelsPlanProcessor(Processor[LabelsPlanPayload, ResultEnvelope[LabelsPlanResult]]):
    """Compute create/update/delete deltas for labels plan."""

    def process(self, payload: LabelsPlanPayload) -> ResultEnvelope[LabelsPlanResult]:
        existing_map = {lab.get("name", ""): lab for lab in payload.existing_labels}
        to_create, to_update = self._compute_creates_updates(payload.desired_labels, existing_map)
        to_delete = self._compute_deletes(payload) if payload.delete_missing else []
        return ResultEnvelope(
            status="success",
            payload=LabelsPlanResult(
                to_create=to_create,
                to_update=to_update,
                to_delete=to_delete,
                show_delete=payload.delete_missing,
            ),
        )

    def _compute_creates_updates(
        self, desired_labels: list[dict], existing_map: dict
    ) -> tuple[list[dict], list[LabelChange]]:
        """Return (to_create, to_update) based on desired vs existing labels."""
        to_create: list[dict] = []
        to_update: list[LabelChange] = []
        for spec in desired_labels:
            name = spec.get("name")
            if not name:
                continue
            current = existing_map.get(name)
            if not current:
                to_create.append(spec)
                continue
            changes = _diff_label(current, spec)
            if changes:
                to_update.append(LabelChange(name=name, changes=changes, spec=spec))
        return to_create, to_update

    def _compute_deletes(self, payload) -> list[str]:
        """Return list of label names to delete (missing from desired)."""
        desired_names = {spec.get("name") for spec in payload.desired_labels if spec.get("name")}
        return [
            lab.get("name")
            for lab in payload.existing_labels
            if not _is_system_label(lab) and lab.get("name") and lab.get("name") not in desired_names
        ]


@dataclass
class LabelsSyncResult:
    plan: LabelsPlanResult
    redirects: list[dict[str, str]]


class LabelsSyncProcessor(Processor[LabelsSyncPayload, ResultEnvelope[LabelsSyncResult]]):
    """Compute sync operations plus redirect sweeps."""

    def process(self, payload: LabelsSyncPayload) -> ResultEnvelope[LabelsSyncResult]:
        plan_envelope = LabelsPlanProcessor().process(payload)
        plan = plan_envelope.payload or LabelsPlanResult([], [], [], show_delete=False)

        redirects: list[dict[str, str]] = []
        if payload.sweep_redirects:
            redirects = [
                r for r in payload.desired_redirects if isinstance(r, dict) and r.get("from") and r.get("to")
            ]

        return ResultEnvelope(status="success", payload=LabelsSyncResult(plan=plan, redirects=redirects))


@dataclass
class LabelsExportResult:
    labels: list[dict]
    redirects: list[dict]
    out_path: Path


class LabelsExportProcessor(Processor[LabelsExportPayload, ResultEnvelope[LabelsExportResult]]):
    """Normalize labels for export."""

    def process(self, payload: LabelsExportPayload) -> ResultEnvelope[LabelsExportResult]:
        clean: list[dict] = []
        for lab in payload.labels:
            if lab.get("type") == "system":
                continue
            entry = {"name": lab.get("name")}
            if lab.get("color"):
                entry["color"] = lab["color"]
            if lab.get("labelListVisibility"):
                entry["labelListVisibility"] = lab["labelListVisibility"]
            if lab.get("messageListVisibility"):
                entry["messageListVisibility"] = lab["messageListVisibility"]
            clean.append(entry)
        return ResultEnvelope(
            status="success",
            payload=LabelsExportResult(labels=clean, redirects=[], out_path=payload.out_path),
        )


def _diff_label(current: dict, desired: dict) -> dict[str, dict[str, str]]:
    changes: dict[str, dict[str, str]] = {}
    for key in ("color", "labelListVisibility", "messageListVisibility"):
        desired_value = desired.get(key)
        if desired_value and current.get(key) != desired_value:
            changes[key] = {"from": current.get(key), "to": desired_value}
    return changes


def _is_system_label(label: dict) -> bool:
    return label.get("type") == "system"
