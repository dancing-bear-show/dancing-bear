"""Producers for labels pipelines."""
from __future__ import annotations

from typing import Dict, List

from core.pipeline import Producer, ResultEnvelope

from ..providers.base import BaseProvider
from ..utils.plan import print_plan_summary
from .processors import (
    LabelChange,
    LabelsPlanResult,
    LabelsSyncResult,
    LabelsExportResult,
)


class LabelsPlanProducer(Producer[ResultEnvelope[LabelsPlanResult]]):
    """Render labels plan output identically to the legacy command."""

    def produce(self, result: ResultEnvelope[LabelsPlanResult]) -> None:
        if not result.ok() or not result.payload:
            print("Labels plan failed.")
            return
        payload = result.payload
        self._print_summary(payload)
        self._print_creates(payload.to_create)
        self._print_updates(payload.to_update)
        self._print_deletes(payload.to_delete)

    def _print_summary(self, payload: LabelsPlanResult) -> None:
        delete_count = len(payload.to_delete) if payload.show_delete else None
        print_plan_summary(
            create=len(payload.to_create),
            update=len(payload.to_update),
            delete=delete_count,
        )

    def _print_creates(self, to_create: List[Dict]) -> None:
        if not to_create:
            return
        print("\nWould create:")
        for spec in to_create[:20]:
            print(f"  {spec.get('name')}")
        if len(to_create) > 20:
            print(f"  … and {len(to_create)-20} more")

    def _print_updates(self, to_update: List[LabelChange]) -> None:
        if not to_update:
            return
        print("\nWould update:")
        for change in to_update[:20]:
            parts = [f"{k}:{v['from']}→{v['to']}" for k, v in change.changes.items()]
            print(f"  {change.name} ({', '.join(parts)})")
        if len(to_update) > 20:
            print(f"  … and {len(to_update)-20} more")

    def _print_deletes(self, to_delete: List[str]) -> None:
        if not to_delete:
            return
        print("\nWould delete:")
        for name in to_delete[:20]:
            print(f"  {name}")
        if len(to_delete) > 20:
            print(f"  … and {len(to_delete)-20} more")


class LabelsSyncProducer(Producer[ResultEnvelope[LabelsSyncResult]]):
    """Apply label creates/updates/deletes plus redirect sweeps."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[LabelsSyncResult]) -> None:
        if not result.ok() or not result.payload:
            print("Labels sync failed.")
            return
        payload = result.payload
        plan = payload.plan
        created = self._apply_creates(plan.to_create)
        updated = self._apply_updates(plan.to_update)
        redirected: set[str] = set()
        if payload.redirects:
            redirected = self._apply_redirects(payload.redirects)
        remaining_to_delete = [name for name in plan.to_delete if name not in redirected]
        deleted = self._apply_deletes(remaining_to_delete)

        print(f"Sync complete. Created: {created}, Updated: {updated}, Deleted: {deleted}.")

    def _apply_creates(self, specs: List[Dict]) -> int:
        count = 0
        for spec in specs:
            name = spec.get("name")
            if not name:
                continue
            body = _label_body_from_spec(spec)
            if self.dry_run:
                print(f"Would create label: {name}")
            else:
                self.client.create_label(**body)
                print(f"Created label: {name}")
            count += 1
        return count

    def _apply_updates(self, changes: List[LabelChange]) -> int:
        count = 0
        for change in changes:
            body = {"name": change.name}
            for key, diff in change.changes.items():
                body[key] = diff["to"]
            if self.dry_run:
                print(f"Would update label: {change.name}")
            else:
                label_id = self.client.get_label_id_map().get(change.name)
                if not label_id:
                    continue
                self.client.update_label(label_id, body)
                print(f"Updated label: {change.name}")
            count += 1
        return count

    def _apply_deletes(self, names: List[str]) -> int:
        count = 0
        for name in names:
            if self.dry_run:
                print(f"Would delete label: {name}")
            else:
                label_id = self.client.get_label_id_map().get(name)
                if label_id:
                    self.client.delete_label(label_id)
                    print(f"Deleted label: {name}")
            count += 1
        return count

    def _apply_redirects(self, redirects: List[Dict[str, str]]) -> set[str]:
        processed: set[str] = set()
        for redirect in redirects:
            old = redirect.get("from")
            new = redirect.get("to")
            if not old or not new or old == new:
                continue
            name_to_id = self.client.get_label_id_map()
            old_id = name_to_id.get(old)
            new_id = name_to_id.get(new) or self.client.ensure_label(new)
            if not old_id or not new_id:
                continue
            ids = self.client.list_message_ids(label_ids=[old_id], max_pages=50, page_size=500)
            if self.dry_run:
                print(f"Would merge '{old}' into '{new}' ({len(ids)} messages).")
                continue
            from ..utils.batch import apply_in_chunks

            apply_in_chunks(
                lambda chunk, nid=new_id, oid=old_id: self.client.batch_modify_messages(
                    chunk, add_label_ids=[nid], remove_label_ids=[oid]
                ),
                ids,
                500,
            )
            try:
                self.client.delete_label(old_id)
                print(f"Merged '{old}' into '{new}' and deleted source label.")
            except Exception as exc:  # pragma: no cover - log only
                print(f"Warning: failed to delete old label '{old}': {exc}")
            processed.add(old)
        return processed


def _label_body_from_spec(spec: Dict) -> Dict:
    body = {"name": spec.get("name")}
    for key in ("color", "labelListVisibility", "messageListVisibility"):
        value = spec.get(key)
        if value:
            body[key] = value
    return body


class LabelsExportProducer(Producer[ResultEnvelope[LabelsExportResult]]):
    """Write labels export YAML."""

    def __init__(self):
        from ..yamlio import dump_config  # lazy import

        self._dump_config = dump_config

    def produce(self, result: ResultEnvelope[LabelsExportResult]) -> None:
        if not result.ok() or not result.payload:
            print("Labels export failed.")
            return
        payload = result.payload
        out = payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        self._dump_config(str(out), {"labels": payload.labels, "redirects": payload.redirects})
        print(f"Exported {len(payload.labels)} labels to {out}")
