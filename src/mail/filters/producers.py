"""Producers for mail filters pipelines.

Plan/sync/impact/export/add-forward producers live here.
Sweep producers are in producers_sweep.py.
Token-update producers are in producers_token.py.
"""
from __future__ import annotations

from pathlib import Path

from core.pipeline import Producer, ResultEnvelope

from ..providers.base import BaseProvider
from ..utils.cli_helpers import preview_criteria
from ..utils.filters import action_to_label_changes
from ..utils.plan import print_plan_summary
from .processors import (
    FilterPlanEntry,
    FiltersPlanResult,
    FiltersSyncResult,
    FiltersImpactResult,
    FiltersExportResult,
)
from .processors_sweep import FiltersAddForwardResult
from .producers_sweep import (  # noqa: F401
    SweepProducerConfig,
    FiltersSweepProducer,
    FiltersSweepRangeProducer,
    FiltersPruneProducer,
)
from .producers_token import (  # noqa: F401
    _produce_token_updates,
    FiltersAddTokenProducer,
    FiltersRemoveTokenProducer,
)

_EMPTY_QUERY = "(empty)"


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

    def _build_action_ids(self, actions: dict[str, object]) -> dict:
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
            query = record.query or _EMPTY_QUERY
            print(f"{record.count:6d}  {query}")
        print(f"Total impacted: {payload.total}")


class FiltersAddForwardProducer(Producer[ResultEnvelope[FiltersAddForwardResult]]):
    """Apply forward actions to matching filters."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersAddForwardResult]) -> None:
        if not result.ok() or not result.payload:
            diagnostics = (result.diagnostics or {}).get("message")
            print(diagnostics if diagnostics else "Filters add-forward failed.")
            return
        payload = result.payload
        from ..utils.cli_helpers import preview_criteria as preview_crit

        changed = sum(
            self._apply_forward_update(update, payload.destination, preview_crit)
            for update in payload.updates
        )
        if not payload.updates:
            print("No matching filters found for given label prefix.")
        else:
            print(f"Updated {changed} filters.")

    def _apply_forward_update(self, update, destination: str, preview_crit) -> int:
        """Apply or preview a single forward update. Returns 1 on success/preview, 0 on error."""
        fid = update.filter_obj.get("id")
        criteria = update.criteria
        action = dict(update.action)
        action["forward"] = destination
        if self.dry_run:
            add_names = update.action.get("addLabelIds") or []
            rem_names = update.action.get("removeLabelIds") or []
            print(
                f"Would update filter id={fid}: "
                f"{preview_crit(criteria)} -> add={add_names} "
                f"remove={rem_names} forward={destination}"
            )
            return 1
        try:
            self.client.create_filter(criteria, action)
            if fid:
                self.client.delete_filter(fid)
            print(f"Updated filter id={fid} (added forward={destination})")
            return 1
        except Exception as exc:  # pragma: no cover - network
            print(f"Failed to update filter id={fid}: {exc}")
            return 0


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
