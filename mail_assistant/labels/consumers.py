from __future__ import annotations

"""Consumers for labels pipelines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from core.pipeline import Consumer

from ..context import MailContext
from ..yamlio import load_config


@dataclass
class LabelsPlanPayload:
    desired_labels: List[dict]
    existing_labels: List[dict]
    delete_missing: bool


@dataclass
class LabelsSyncPayload(LabelsPlanPayload):
    desired_redirects: List[dict]
    sweep_redirects: bool


@dataclass
class LabelsExportPayload:
    labels: List[dict]
    out_path: Path


class LabelsPlanConsumer(Consumer[LabelsPlanPayload]):
    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> LabelsPlanPayload:
        payload = _load_labels_payload(
            self.context,
            error_hint="Config missing 'labels' list; nothing to plan.",
            allow_missing=True,
        )
        return LabelsPlanPayload(
            desired_labels=payload["desired_labels"],
            existing_labels=payload["existing_labels"],
            delete_missing=payload["delete_missing"],
        )


class LabelsSyncConsumer(Consumer[LabelsSyncPayload]):
    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> LabelsSyncPayload:
        payload = _load_labels_payload(
            self.context,
            error_hint="Config missing 'labels' list; nothing to sync.",
            allow_missing=False,
        )
        return LabelsSyncPayload(**payload)


class LabelsExportConsumer(Consumer[LabelsExportPayload]):
    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> LabelsExportPayload:
        client = self.context.get_gmail_client()
        labels = [lab for lab in client.list_labels() if isinstance(lab, dict)]
        out = getattr(self.context.args, "out", None)
        if not out:
            raise ValueError("Missing --out for labels export.")
        return LabelsExportPayload(labels=labels, out_path=Path(out))


def _load_labels_payload(context: MailContext, *, error_hint: str, allow_missing: bool) -> dict:
    args = context.args
    cfg = load_config(getattr(args, "config", None))
    desired_labels = _load_desired(cfg, key="labels", error_hint=error_hint, allow_missing=allow_missing)
    desired_redirects = _load_desired(cfg, key="redirects", error_hint="", allow_missing=True)

    client = context.get_gmail_client()
    existing = [lab for lab in client.list_labels() if isinstance(lab, dict)]
    delete_missing = bool(getattr(args, "delete_missing", False))
    sweep_redirects = bool(getattr(args, "sweep_redirects", False))

    return {
        "desired_labels": desired_labels,
        "desired_redirects": desired_redirects,
        "existing_labels": existing,
        "delete_missing": delete_missing,
        "sweep_redirects": sweep_redirects,
    }


def _load_desired(cfg: dict, *, key: str, error_hint: str, allow_missing: bool) -> List[dict]:
    data = cfg.get(key)
    if data is None:
        return []
    if not isinstance(data, list):
        if allow_missing:
            return []
        raise ValueError(error_hint or f"Config missing '{key}' list.")
    result: List[dict] = []
    for entry in data:
        if isinstance(entry, dict):
            result.append(entry)
    return result
