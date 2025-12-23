"""Producers for mail filters pipelines."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import time

from core.pipeline import Producer, ResultEnvelope

from ..providers.base import BaseProvider
from ..utils.batch import apply_in_chunks
from ..utils.gmail_ops import list_message_ids as _list_message_ids_shared
from ..utils.cli_helpers import preview_criteria
from ..utils.filters import action_to_label_changes
from ..utils.plan import print_plan_summary
from .processors import (
    FilterPlanEntry,
    FiltersPlanResult,
    FiltersSyncResult,
    FiltersImpactResult,
    FiltersExportResult,
    FiltersSweepResult,
    FiltersSweepRangeResult,
    FiltersPruneResult,
    FiltersAddForwardResult,
    FiltersAddTokenResult,
    FiltersRemoveTokenResult,
)


class FiltersPlanProducer(Producer[ResultEnvelope[FiltersPlanResult]]):
    """Render plan results in the legacy human-readable format."""

    def __init__(self, preview_limit: int = 20):
        self.preview_limit = preview_limit

    def produce(self, result: ResultEnvelope[FiltersPlanResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters plan failed.")
            return
        payload = result.payload
        print_plan_summary(create=len(payload.to_create), delete=len(payload.to_delete))
        if payload.add_counts:
            print("Adds distribution:")
            for name, count in payload.add_counts.most_common():
                print(f"  {name}: {count}")

        if payload.to_create:
            print("\nWould create:")
            for entry in payload.to_create[: self.preview_limit]:
                self._print_create_entry(entry)
            remaining = len(payload.to_create) - self.preview_limit
            if remaining > 0:
                print(f"  … and {remaining} more")

        if payload.to_delete:
            print("\nWould delete (not present in YAML):")
            for filter_entry in payload.to_delete[: self.preview_limit]:
                self._print_delete_entry(filter_entry, payload.id_to_name)
            remaining = len(payload.to_delete) - self.preview_limit
            if remaining > 0:
                print(f"  … and {remaining} more")

    def _print_create_entry(self, entry: FilterPlanEntry) -> None:
        actions = entry.action_names
        add = actions.get("add") or []
        remove = actions.get("remove") or []
        forward = actions.get("forward")
        print(
            f"  {preview_criteria(entry.criteria)} -> "
            f"add={add} remove={remove} forward={forward}"
        )

    def _print_delete_entry(self, entry: dict, id_to_name: dict[str, str]) -> None:
        crit = entry.get("criteria", {}) or {}
        action = entry.get("action", {}) or {}
        add_names = [id_to_name.get(x, x) for x in (action.get("addLabelIds") or [])]
        remove_names = [id_to_name.get(x, x) for x in (action.get("removeLabelIds") or [])]
        forward = action.get("forward")
        print(
            f"  {preview_criteria(crit)} -> "
            f"add={add_names} remove={remove_names} forward={forward}"
        )


class FiltersSyncProducer(Producer[ResultEnvelope[FiltersSyncResult]]):
    """Apply create/delete operations for filters sync."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersSyncResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters sync failed.")
            return

        payload = result.payload
        created = self._apply_creates(payload.to_create)
        deleted = self._apply_deletes(payload.to_delete)
        print(f"Filters sync complete. Created: {created}, Deleted: {deleted}.")

    def _apply_creates(self, entries: list[FilterPlanEntry]) -> int:
        created = 0
        for entry in entries:
            actions = entry.action_names
            if self.dry_run:
                print(f"Would create filter: criteria={entry.criteria} action={actions}")
            else:
                act_ids = self._build_action_ids(actions)
                self.client.create_filter(entry.criteria, act_ids)
                print("Created filter.")
            created += 1
        return created

    def _apply_deletes(self, entries: list[dict]) -> int:
        deleted = 0
        for existing in entries:
            fid = existing.get("id")
            if self.dry_run:
                print(f"Would delete filter: id={fid}")
            else:
                if fid:
                    self.client.delete_filter(fid)
                    print(f"Deleted filter: id={fid}")
            deleted += 1
        return deleted

    def _build_action_ids(self, actions: Dict[str, object]) -> dict:
        add = list(actions.get("add") or [])
        remove = list(actions.get("remove") or [])
        act_ids: dict = {}
        if add or remove:
            add_ids, rem_ids = action_to_label_changes(self.client, {"add": add, "remove": remove})
            if add_ids:
                act_ids["addLabelIds"] = add_ids
            if rem_ids:
                act_ids["removeLabelIds"] = rem_ids
        forward = actions.get("forward")
        if forward:
            act_ids["forward"] = forward
        return act_ids


class FiltersImpactProducer(Producer[ResultEnvelope[FiltersImpactResult]]):
    """Render impact counts for filters."""

    def produce(self, result: ResultEnvelope[FiltersImpactResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters impact failed.")
            return
        payload = result.payload
        for record in payload.records:
            query = record.query or "(empty)"
            print(f"{record.count:6d}  {query}")
        print(f"Total impacted: {payload.total}")


class FiltersSweepProducer(Producer[ResultEnvelope[FiltersSweepResult]]):
    """Apply sweep actions to historical messages."""

    def __init__(
        self,
        client: BaseProvider,
        *,
        pages: int,
        batch_size: int,
        max_msgs: int | None,
        dry_run: bool = False,
    ):
        self.client = client
        self.pages = pages
        self.batch_size = batch_size
        self.max_msgs = max_msgs
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersSweepResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters sweep failed.")
            return
        total = 0
        for instruction in result.payload.instructions:
            ids = _list_message_ids_shared(
                self.client,
                query=instruction.query,
                pages=self.pages,
                max_msgs=self.max_msgs,
            )
            query_display = instruction.query if instruction.query else "(empty)"
            if self.dry_run:
                print(
                    f"Query: {query_display} => {len(ids)} messages; "
                    f"+{instruction.add_label_ids} -{instruction.remove_label_ids}"
                )
            else:
                apply_in_chunks(
                    lambda chunk: self.client.batch_modify_messages(
                        chunk,
                        add_label_ids=instruction.add_label_ids,
                        remove_label_ids=instruction.remove_label_ids,
                    ),
                    ids,
                    self.batch_size,
                )
                print(f"Modified {len(ids)} messages for rule")
            total += len(ids)
        print(f"Sweep complete. Modified {total} messages total.")


class FiltersSweepRangeProducer(Producer[ResultEnvelope[FiltersSweepRangeResult]]):
    """Apply sweep actions across multiple windows."""

    def __init__(
        self,
        client: BaseProvider,
        *,
        pages: int,
        batch_size: int,
        max_msgs: int | None,
        dry_run: bool = False,
    ):
        self.client = client
        self.pages = pages
        self.batch_size = batch_size
        self.max_msgs = max_msgs
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersSweepRangeResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters sweep-range failed.")
            return
        total = 0
        for window in result.payload.windows:
            print(f"\nWindow: {window.label}")
            window_total = 0
            for instruction in window.instructions:
                ids = _list_message_ids_shared(
                    self.client,
                    query=instruction.query,
                    pages=self.pages,
                    max_msgs=self.max_msgs,
                )
                if self.dry_run:
                    query_display = instruction.query if instruction.query else "(empty)"
                    print(
                        f"  {len(ids)} msgs; +{instruction.add_label_ids} "
                        f"-{instruction.remove_label_ids} | {query_display}"
                    )
                else:
                    apply_in_chunks(
                        lambda chunk: self.client.batch_modify_messages(
                            chunk,
                            add_label_ids=instruction.add_label_ids,
                            remove_label_ids=instruction.remove_label_ids,
                        ),
                        ids,
                        self.batch_size,
                    )
                window_total += len(ids)
            print(f"Window modified: {window_total}")
            total += window_total
        print(f"Total modified across windows: {total}")


class FiltersPruneProducer(Producer[ResultEnvelope[FiltersPruneResult]]):
    """Delete filters that match no messages."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersPruneResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters prune failed.")
            return
        payload = result.payload
        total = len(payload.candidates)
        deleted = 0
        for cand in payload.candidates:
            if not cand.is_empty:
                continue
            fid = cand.filter_obj.get("id")
            query_display = cand.query if cand.query else "(empty)"
            if self.dry_run:
                print(f"Would delete filter id={fid} | {query_display}")
            else:
                if self._delete_with_retry(fid):
                    deleted += 1
        print(f"Prune complete. Examined: {total} Deleted: {deleted}")

    def _delete_with_retry(self, fid: str | None) -> bool:
        if not fid:
            return False
        last_err = None
        for attempt in range(3):
            try:
                self.client.delete_filter(fid)
                print(f"Deleted filter id={fid}")
                return True
            except Exception as exc:  # pragma: no cover - retry logging
                last_err = exc
                time.sleep(1.5 * (2 ** attempt))
        print(f"Warning: failed to delete filter id={fid}: {last_err}")
        return False


class FiltersAddForwardProducer(Producer[ResultEnvelope[FiltersAddForwardResult]]):
    """Apply forward actions to matching filters."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersAddForwardResult]) -> None:
        if not result.ok() or not result.payload:
            diagnostics = (result.diagnostics or {}).get("message")
            if diagnostics:
                print(diagnostics)
            else:
                print("Filters add-forward failed.")
            return
        payload = result.payload
        from ..utils.cli_helpers import preview_criteria as preview_crit

        changed = 0
        for update in payload.updates:
            fid = update.filter_obj.get("id")
            criteria = update.criteria
            action = dict(update.action)
            action["forward"] = payload.destination
            add_names = update.action.get("addLabelIds") or []
            rem_names = update.action.get("removeLabelIds") or []
            if self.dry_run:
                print(
                    f"Would update filter id={fid}: "
                    f"{preview_crit(criteria)} -> add={add_names} "
                    f"remove={rem_names} forward={payload.destination}"
                )
                changed += 1
                continue
            try:
                self.client.create_filter(criteria, action)
                if fid:
                    self.client.delete_filter(fid)
                print(f"Updated filter id={fid} (added forward={payload.destination})")
                changed += 1
            except Exception as exc:  # pragma: no cover - network
                print(f"Failed to update filter id={fid}: {exc}")
        if not payload.updates:
            print("No matching filters found for given label prefix.")
        else:
            print(f"Updated {changed} filters.")


class FiltersAddTokenProducer(Producer[ResultEnvelope[FiltersAddTokenResult]]):
    """Apply add-from-token updates."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersAddTokenResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters add-from-token failed.")
            return
        _produce_token_updates(self.client, result.payload.updates, self.dry_run)


class FiltersRemoveTokenProducer(Producer[ResultEnvelope[FiltersRemoveTokenResult]]):
    """Apply rm-from-token updates."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersRemoveTokenResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters rm-from-token failed.")
            return
        _produce_token_updates(self.client, result.payload.updates, self.dry_run)


def _produce_token_updates(client: BaseProvider, updates: List[FilterTokenUpdate], dry_run: bool) -> None:
    from ..utils.cli_helpers import preview_criteria as preview_crit

    changed = 0
    for update in updates:
        fid = update.filter_obj.get("id")
        if dry_run:
            print(
                f"Would update filter id={fid}: "
                f"{preview_crit(update.criteria)} -> from: {update.new_from}"
            )
            changed += 1
            continue
        try:
            client.create_filter(update.criteria, update.action)
            if fid:
                client.delete_filter(fid)
            print(f"Updated filter id={fid}: set from={update.new_from}")
            changed += 1
        except Exception as exc:  # pragma: no cover - network
            print(f"Failed to update filter id={fid}: {exc}")
    print(f"Updated {changed} filters.")

    def _delete_with_retry(self, fid: str | None) -> bool:
        if not fid:
            return False
        last_err = None
        for attempt in range(3):
            try:
                self.client.delete_filter(fid)
                print(f"Deleted filter id={fid}")
                return True
            except Exception as exc:  # pragma: no cover - retry logging
                last_err = exc
                time.sleep(1.5 * (2 ** attempt))
        print(f"Warning: failed to delete filter id={fid}: {last_err}")
        return False


class FiltersExportProducer(Producer[ResultEnvelope[FiltersExportResult]]):
    """Write filter DSL export."""

    def __init__(self):
        from ..yamlio import dump_config  # lazy import

        self._dump_config = dump_config

    def produce(self, result: ResultEnvelope[FiltersExportResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters export failed.")
            return
        payload = result.payload
        out = payload.out_path
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._dump_config(str(path), {"filters": payload.filters})
        print(f"Exported {len(payload.filters)} filters to {path}")
