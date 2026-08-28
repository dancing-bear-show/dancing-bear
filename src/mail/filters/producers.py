"""Producers for mail filters pipelines.

Plan/sync/impact/export/add-forward producers live here.
Sweep producers are in producers_sweep.py.
Token-update producers are in producers_token.py.
"""
from __future__ import annotations

from pathlib import Path

from core.cli_output import OutputWriter
from core.pipeline import BaseProducer

from ..providers.base import BaseProvider
from ..utils.cli_helpers import preview_criteria
from ..utils.filters import action_to_label_changes
from ..utils.plan import print_plan_summary
from .processors_plan import (
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


class FiltersPlanProducer(BaseProducer):
    """Render plan results in the legacy human-readable format."""

    failure_message = "Filters plan failed."

    def __init__(self, preview_limit: int = 20, writer: OutputWriter | None = None):
        super().__init__(writer)
        self.preview_limit = preview_limit

    def _produce_success(self, payload: FiltersPlanResult, diagnostics: dict | None) -> None:
        print_plan_summary(create=len(payload.to_create), delete=len(payload.to_delete))
        if payload.add_counts:
            self._writer.print("Adds distribution:")
            for name, count in payload.add_counts.most_common():
                self._writer.print(f"  {name}: {count}")

        if payload.to_create:
            self._writer.print("\nWould create:")
            for entry in payload.to_create[: self.preview_limit]:
                self._print_create_entry(entry)
            remaining = len(payload.to_create) - self.preview_limit
            if remaining > 0:
                self._writer.print(f"  … and {remaining} more")

        if payload.to_delete:
            self._writer.print("\nWould delete (not present in YAML):")
            for filter_entry in payload.to_delete[: self.preview_limit]:
                self._print_delete_entry(filter_entry, payload.id_to_name)
            remaining = len(payload.to_delete) - self.preview_limit
            if remaining > 0:
                self._writer.print(f"  … and {remaining} more")

    def _print_create_entry(self, entry: FilterPlanEntry) -> None:
        actions = entry.action_names
        add = actions.get("add") or []
        remove = actions.get("remove") or []
        forward = actions.get("forward")
        self._writer.print(
            f"  {preview_criteria(entry.criteria)} -> "
            f"add={add} remove={remove} forward={forward}"
        )

    def _print_delete_entry(self, entry: dict, id_to_name: dict[str, str]) -> None:
        crit = entry.get("criteria", {}) or {}
        action = entry.get("action", {}) or {}
        add_names = [id_to_name.get(x, x) for x in (action.get("addLabelIds") or [])]
        remove_names = [id_to_name.get(x, x) for x in (action.get("removeLabelIds") or [])]
        forward = action.get("forward")
        self._writer.print(
            f"  {preview_criteria(crit)} -> "
            f"add={add_names} remove={remove_names} forward={forward}"
        )


class FiltersSyncProducer(BaseProducer):
    """Apply create/delete operations for filters sync."""

    failure_message = "Filters sync failed."

    def __init__(self, client: BaseProvider, *, dry_run: bool = False, writer: OutputWriter | None = None):
        super().__init__(writer)
        self.client = client
        self.dry_run = dry_run

    def _produce_success(self, payload: FiltersSyncResult, diagnostics: dict | None) -> None:
        created = self._apply_creates(payload.to_create)
        deleted = self._apply_deletes(payload.to_delete)
        self._writer.print(f"Filters sync complete. Created: {created}, Deleted: {deleted}.")

    def _apply_creates(self, entries: list[FilterPlanEntry]) -> int:
        created = 0
        for entry in entries:
            actions = entry.action_names
            if self.dry_run:
                self._writer.print_dry_run(f"create filter: criteria={entry.criteria} action={actions}")
            else:
                act_ids = self._build_action_ids(actions)
                self.client.create_filter(entry.criteria, act_ids)
                self._writer.print("Created filter.")
            created += 1
        return created

    def _apply_deletes(self, entries: list[dict]) -> int:
        deleted = 0
        for existing in entries:
            fid = existing.get("id")
            if self.dry_run:
                self._writer.print_dry_run(f"delete filter: id={fid}")
            else:
                if fid:
                    self.client.delete_filter(fid)
                    self._writer.print(f"Deleted filter: id={fid}")
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


class FiltersImpactProducer(BaseProducer):
    """Render impact counts for filters."""

    failure_message = "Filters impact failed."

    def _produce_success(self, payload: FiltersImpactResult, diagnostics: dict | None) -> None:
        for record in payload.records:
            query = record.query or _EMPTY_QUERY
            self._writer.print(f"{record.count:6d}  {query}")
        self._writer.print(f"Total impacted: {payload.total}")


class FiltersAddForwardProducer(BaseProducer):
    """Apply forward actions to matching filters."""

    failure_message = "Filters add-forward failed."

    def __init__(self, client: BaseProvider, *, dry_run: bool = False, writer: OutputWriter | None = None):
        super().__init__(writer)
        self.client = client
        self.dry_run = dry_run

    def _produce_success(self, payload: FiltersAddForwardResult, diagnostics: dict | None) -> None:
        from ..utils.cli_helpers import preview_criteria as preview_crit

        changed = sum(
            self._apply_forward_update(update, payload.destination, preview_crit)
            for update in payload.updates
        )
        if not payload.updates:
            self._writer.print("No matching filters found for given label prefix.")
        else:
            self._writer.print(f"Updated {changed} filters.")

    def _apply_forward_update(self, update, destination: str, preview_crit) -> int:
        """Apply or preview a single forward update. Returns 1 on success/preview, 0 on error."""
        fid = update.filter_obj.get("id")
        criteria = update.criteria
        action = dict(update.action)
        action["forward"] = destination
        if self.dry_run:
            add_names = update.action.get("addLabelIds") or []
            rem_names = update.action.get("removeLabelIds") or []
            self._writer.print_dry_run(
                f"update filter id={fid}: "
                f"{preview_crit(criteria)} -> add={add_names} "
                f"remove={rem_names} forward={destination}"
            )
            return 1
        try:
            self.client.create_filter(criteria, action)
            if fid:
                self.client.delete_filter(fid)
            self._writer.print(f"Updated filter id={fid} (added forward={destination})")
            return 1
        except Exception as exc:  # pragma: no cover - network
            self._writer.print_error(f"Failed to update filter id={fid}: {exc}")
            return 0


class FiltersExportProducer(BaseProducer):
    """Write filter DSL export."""

    failure_message = "Filters export failed."

    def __init__(self, writer: OutputWriter | None = None):
        from core.yamlio import dump_config  # lazy import

        super().__init__(writer)
        self._dump_config = dump_config

    def _produce_success(self, payload: FiltersExportResult, diagnostics: dict | None) -> None:
        path = Path(payload.out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._dump_config(str(path), {"filters": payload.filters})
        self._writer.print(f"Exported {len(payload.filters)} filters to {path}")
