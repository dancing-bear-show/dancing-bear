from __future__ import annotations

"""Processors for labels pipelines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from core.pipeline import Processor, ResultEnvelope

from .consumers import LabelsPlanPayload, LabelsSyncPayload, LabelsExportPayload


@dataclass
class LabelChange:
    name: str
    changes: Dict[str, Dict[str, str]]
    spec: Dict


@dataclass
class LabelsPlanResult:
    to_create: List[Dict]
    to_update: List[LabelChange]
    to_delete: List[str]
    show_delete: bool


class LabelsPlanProcessor(Processor[LabelsPlanPayload, ResultEnvelope[LabelsPlanResult]]):
    """Compute create/update/delete deltas for labels plan."""

    def process(self, payload: LabelsPlanPayload) -> ResultEnvelope[LabelsPlanResult]:
        existing_map = {lab.get("name", ""): lab for lab in payload.existing_labels}
        to_create: List[Dict] = []
        to_update: List[LabelChange] = []

        for spec in payload.desired_labels:
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

        to_delete: List[str] = []
        if payload.delete_missing:
            desired_names = {spec.get("name") for spec in payload.desired_labels if spec.get("name")}
            for lab in payload.existing_labels:
                if _is_system_label(lab):
                    continue
                name = lab.get("name")
                if name and name not in desired_names:
                    to_delete.append(name)

        return ResultEnvelope(
            status="success",
            payload=LabelsPlanResult(
                to_create=to_create,
                to_update=to_update,
                to_delete=to_delete,
                show_delete=payload.delete_missing,
            ),
        )


@dataclass
class LabelsSyncResult:
    plan: LabelsPlanResult
    redirects: List[Dict[str, str]]


class LabelsSyncProcessor(Processor[LabelsSyncPayload, ResultEnvelope[LabelsSyncResult]]):
    """Compute sync operations plus redirect sweeps."""

    def process(self, payload: LabelsSyncPayload) -> ResultEnvelope[LabelsSyncResult]:
        plan_envelope = LabelsPlanProcessor().process(payload)
        plan = plan_envelope.payload or LabelsPlanResult([], [], [])

        redirects: List[Dict[str, str]] = []
        if payload.sweep_redirects:
            redirects = [
                r for r in payload.desired_redirects if isinstance(r, dict) and r.get("from") and r.get("to")
            ]

        return ResultEnvelope(status="success", payload=LabelsSyncResult(plan=plan, redirects=redirects))


@dataclass
class LabelsExportResult:
    labels: List[dict]
    redirects: List[dict]
    out_path: Path


class LabelsExportProcessor(Processor[LabelsExportPayload, ResultEnvelope[LabelsExportResult]]):
    """Normalize labels for export."""

    def process(self, payload: LabelsExportPayload) -> ResultEnvelope[LabelsExportResult]:
        clean: List[dict] = []
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


def _diff_label(current: Dict, desired: Dict) -> Dict[str, Dict[str, str]]:
    changes: Dict[str, Dict[str, str]] = {}
    for key in ("color", "labelListVisibility", "messageListVisibility"):
        desired_value = desired.get(key)
        if desired_value and current.get(key) != desired_value:
            changes[key] = {"from": current.get(key), "to": desired_value}
    return changes


def _is_system_label(label: Dict) -> bool:
    return label.get("type") == "system"
