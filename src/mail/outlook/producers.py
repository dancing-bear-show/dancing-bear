"""Producers for Outlook pipelines."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, ResultEnvelope, diagnostic_message

from .processors_rules import (
    OutlookRulesListResult,
    OutlookRulesExportResult,
)
from .processors_rules_write import (
    OutlookRulesSyncResult,
    OutlookRulesPlanResult,
    OutlookRulesDeleteResult,
    OutlookRulesSweepResult,
)
from .processors_calendar import (
    OutlookCategoriesListResult,
    OutlookCategoriesExportResult,
    OutlookCategoriesSyncResult,
    OutlookFoldersSyncResult,
    OutlookCalendarAddResult,
    OutlookCalendarAddRecurringResult,
    OutlookCalendarAddFromConfigResult,
)


class _CreatedSkipped:
    """Result payloads that carry created/skipped tallies.

    Declared as a duck-type check; produce() only reads the tallies.
    """

    @property
    def created(self) -> int: ...

    @property
    def skipped(self) -> int: ...


_SyncResultT = TypeVar("_SyncResultT", bound=_CreatedSkipped)


def _format_rule_criteria(criteria: dict[str, Any]) -> str:
    """Format rule criteria for display.

    Always includes from/to/subject fields to preserve stable tab-separated format,
    using empty strings when values are not present.
    """
    parts = []
    for k in ("from", "to", "subject"):
        val = criteria.get(k) or ""
        parts.append(f"{k}={val}")
    return "\t".join(parts)


def _format_rule_details(
    action: dict[str, Any],
    id_to_name: dict[str, str],
    folder_path_rev: dict[str, str],
) -> str:
    """Format rule action details for display."""
    cats = []
    for cid in (action.get("addLabelIds") or []):
        nm = id_to_name.get(cid) or cid
        cats.append(nm)

    forward = action.get("forward") or None
    move = action.get("moveToFolderId") or None
    move_name = folder_path_rev.get(move) if move else None

    if not (cats or forward or move):
        return ""

    details = []
    if cats:
        details.append("categories=" + ",".join(cats))
    if forward:
        details.append("forward=" + forward)
    if move:
        details.append("moveToFolder=" + (move_name or move))

    return "  " + " ".join(details)


class OutlookRulesListProducer(BaseProducer):
    """Produce rules list output."""

    failure_message = "Failed to list rules."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookRulesListResult, diagnostics: dict | None) -> None:
        rules = payload.rules
        if not rules:
            self._writer.print("No Inbox rules found.")
            return
        self._print_rules(rules, payload.id_to_name, payload.folder_path_rev)

    def _print_rules(
        self, rules: list[dict[str, Any]], id_to_name: dict[str, str], folder_path_rev: dict[str, str]
    ) -> None:
        """Print formatted rules."""
        for r in rules:
            rid = r.get("id", "")
            crit = r.get("criteria") or {}
            act = r.get("action") or {}

            self._writer.print(f"{rid}\t{_format_rule_criteria(crit)}")
            details = _format_rule_details(act, id_to_name, folder_path_rev)
            if details:
                self._writer.print(details)


class OutlookRulesExportProducer(BaseProducer):
    """Produce rules export output."""

    failure_message = "Failed to export rules."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookRulesExportResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Exported {payload.count} rules to {payload.out_path}")


class OutlookRulesSyncProducer(BaseProducer):
    """Produce rules sync output."""

    failure_message = "Failed to sync rules."

    def __init__(
        self,
        dry_run: bool = False,
        delete_missing: bool = False,
        writer: OutputWriter | None = None,
    ) -> None:
        super().__init__(writer)
        self._dry_run = dry_run
        self._delete_missing = delete_missing

    def produce(self, result: ResultEnvelope) -> None:
        """Override to also surface the hint diagnostic."""
        if not result.ok() or result.payload is None:
            msg = diagnostic_message(result.diagnostics) or self.failure_message
            if msg:
                self._writer.print_error(msg)
            diag = result.diagnostics or {}
            if diag.get("hint"):
                self._writer.print(f"Hint: {diag['hint']}")
            return
        self._produce_success(result.payload, result.diagnostics)

    def _produce_success(self, payload: OutlookRulesSyncResult, diagnostics: dict | None) -> None:
        msg = f"Sync complete. Created: {payload.created}"
        if self._delete_missing:
            msg += f", Deleted: {payload.deleted}"
        if self._dry_run:
            self._writer.print_dry_run(f"sync. Created: {payload.created}" + (f", Deleted: {payload.deleted}" if self._delete_missing else ""))
        else:
            self._writer.print(msg)


class OutlookRulesPlanProducer(BaseProducer):
    """Produce rules plan output."""

    failure_message = "Failed to plan rules."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookRulesPlanResult, diagnostics: dict | None) -> None:
        for item in payload.plan_items:
            self._writer.print(item)
        self._writer.print(f"Plan summary: create={payload.would_create}")


class OutlookRulesDeleteProducer(BaseProducer):
    """Produce rules delete output."""

    failure_message = "Failed to delete Outlook rule."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookRulesDeleteResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Deleted Outlook rule: {payload.rule_id}")


class OutlookRulesSweepProducer(BaseProducer):
    """Produce rules sweep output."""

    failure_message = "Failed to sweep."

    def __init__(self, dry_run: bool = False, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._dry_run = dry_run

    def _produce_success(self, payload: OutlookRulesSweepResult, diagnostics: dict | None) -> None:
        if self._dry_run:
            self._writer.print_dry_run(f"move={payload.moved}")
        else:
            self._writer.print(f"Sweep summary: moved={payload.moved}")


class OutlookCategoriesListProducer(BaseProducer):
    """Produce categories list output."""

    failure_message = "Failed to list categories."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookCategoriesListResult, diagnostics: dict | None) -> None:
        cats = payload.categories
        if not cats:
            self._writer.print("No categories.")
            return
        for c in cats:
            name = c.get("name", "")
            cid = c.get("id", "")
            self._writer.print(f"{cid}\t{name}")


class OutlookCategoriesExportProducer(BaseProducer):
    """Produce categories export output."""

    failure_message = "Failed to export categories."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookCategoriesExportResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Exported {payload.count} categories to {payload.out_path}")


class _CreatedSkippedSyncProducer(BaseProducer, Generic[_SyncResultT]):
    """Report a created/skipped sync tally, or the failure diagnostic.

    Subclasses supply the two messages that vary between sync targets.
    """

    _done_prefix: str = ""

    def __init__(self, dry_run: bool = False, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._dry_run = dry_run

    def _produce_success(self, payload: _SyncResultT, diagnostics: dict | None) -> None:
        summary = f"Created: {payload.created}, Skipped: {payload.skipped}"
        if self._dry_run:
            self._writer.print_dry_run(f"sync. {summary}")
        else:
            self._writer.print(f"{self._done_prefix}. {summary}")


class OutlookCategoriesSyncProducer(_CreatedSkippedSyncProducer[OutlookCategoriesSyncResult]):
    """Produce categories sync output."""

    failure_message = "Failed to sync categories."
    _done_prefix = "Categories sync complete"


class OutlookFoldersSyncProducer(_CreatedSkippedSyncProducer[OutlookFoldersSyncResult]):
    """Produce folders sync output."""

    failure_message = "Failed to sync folders."
    _done_prefix = "Folders sync complete"


class OutlookCalendarAddProducer(BaseProducer):
    """Produce calendar add output."""

    failure_message = "Failed to create event."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookCalendarAddResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Created event: {payload.event_id} subject={payload.subject}")


class OutlookCalendarAddRecurringProducer(BaseProducer):
    """Produce calendar add recurring output."""

    failure_message = "Failed to create recurring event."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookCalendarAddRecurringResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Created recurring series: {payload.event_id} subject={payload.subject}")


class OutlookCalendarAddFromConfigProducer(BaseProducer):
    """Produce calendar add from config output."""

    failure_message = "Failed to add events from config."

    def __init__(self, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)

    def _produce_success(self, payload: OutlookCalendarAddFromConfigResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Created {payload.created} events/series from config")
