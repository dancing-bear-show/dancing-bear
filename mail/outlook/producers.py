"""Producers for Outlook pipelines."""
from __future__ import annotations

from core.pipeline import Producer, ResultEnvelope

from .processors import (
    OutlookRulesListResult,
    OutlookRulesExportResult,
    OutlookRulesSyncResult,
    OutlookRulesPlanResult,
    OutlookRulesDeleteResult,
    OutlookRulesSweepResult,
    OutlookCategoriesListResult,
    OutlookCategoriesExportResult,
    OutlookCategoriesSyncResult,
    OutlookFoldersSyncResult,
    OutlookCalendarAddResult,
    OutlookCalendarAddRecurringResult,
    OutlookCalendarAddFromConfigResult,
)


class OutlookRulesListProducer(Producer[ResultEnvelope[OutlookRulesListResult]]):
    """Produce rules list output."""

    def produce(self, result: ResultEnvelope[OutlookRulesListResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to list rules.')}")
            return

        rules = result.payload.rules
        if not rules:
            print("No Inbox rules found.")
            return

        id_to_name = result.payload.id_to_name
        folder_path_rev = result.payload.folder_path_rev

        for r in rules:
            rid = r.get("id", "")
            crit = r.get("criteria") or {}
            act = r.get("action") or {}
            cats = []
            for cid in (act.get("addLabelIds") or []):
                nm = id_to_name.get(cid) or cid
                cats.append(nm)
            forward = act.get("forward") or None
            move = act.get("moveToFolderId") or None
            move_name = folder_path_rev.get(move) if move else None

            print(f"{rid}\tfrom={crit.get('from') or ''}\tto={crit.get('to') or ''}\tsubject={crit.get('subject') or ''}")
            if cats or forward or move:
                details = []
                if cats:
                    details.append("categories=" + ",".join(cats))
                if forward:
                    details.append("forward=" + forward)
                if move:
                    details.append("moveToFolder=" + (move_name or move))
                print("  " + " ".join(details))


class OutlookRulesExportProducer(Producer[ResultEnvelope[OutlookRulesExportResult]]):
    """Produce rules export output."""

    def produce(self, result: ResultEnvelope[OutlookRulesExportResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to export rules.')}")
            return

        print(f"Exported {result.payload.count} rules to {result.payload.out_path}")


class OutlookRulesSyncProducer(Producer[ResultEnvelope[OutlookRulesSyncResult]]):
    """Produce rules sync output."""

    def __init__(self, dry_run: bool = False, delete_missing: bool = False):
        self._dry_run = dry_run
        self._delete_missing = delete_missing

    def produce(self, result: ResultEnvelope[OutlookRulesSyncResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            error = diag.get("error", "Failed to sync rules.")
            print(f"Error: {error}")
            if diag.get("hint"):
                print(f"Hint: {diag.get('hint')}")
            return

        payload = result.payload
        prefix = "Would sync" if self._dry_run else "Sync complete"
        msg = f"{prefix}. Created: {payload.created}"
        if self._delete_missing:
            msg += f", Deleted: {payload.deleted}"
        print(msg)


class OutlookRulesPlanProducer(Producer[ResultEnvelope[OutlookRulesPlanResult]]):
    """Produce rules plan output."""

    def produce(self, result: ResultEnvelope[OutlookRulesPlanResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to plan rules.')}")
            return

        for item in result.payload.plan_items:
            print(item)
        print(f"Plan summary: create={result.payload.would_create}")


class OutlookRulesDeleteProducer(Producer[ResultEnvelope[OutlookRulesDeleteResult]]):
    """Produce rules delete output."""

    def produce(self, result: ResultEnvelope[OutlookRulesDeleteResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error deleting Outlook rule: {diag.get('error', 'unknown error')}")
            return

        print(f"Deleted Outlook rule: {result.payload.rule_id}")


class OutlookRulesSweepProducer(Producer[ResultEnvelope[OutlookRulesSweepResult]]):
    """Produce rules sweep output."""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    def produce(self, result: ResultEnvelope[OutlookRulesSweepResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to sweep.')}")
            return

        prefix = "Would move" if self._dry_run else "Sweep summary: moved"
        print(f"{prefix}={result.payload.moved}")


class OutlookCategoriesListProducer(Producer[ResultEnvelope[OutlookCategoriesListResult]]):
    """Produce categories list output."""

    def produce(self, result: ResultEnvelope[OutlookCategoriesListResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to list categories.')}")
            return

        cats = result.payload.categories
        if not cats:
            print("No categories.")
            return

        for c in cats:
            name = c.get("name", "")
            cid = c.get("id", "")
            print(f"{cid}\t{name}")


class OutlookCategoriesExportProducer(Producer[ResultEnvelope[OutlookCategoriesExportResult]]):
    """Produce categories export output."""

    def produce(self, result: ResultEnvelope[OutlookCategoriesExportResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to export categories.')}")
            return

        print(f"Exported {result.payload.count} categories to {result.payload.out_path}")


class OutlookCategoriesSyncProducer(Producer[ResultEnvelope[OutlookCategoriesSyncResult]]):
    """Produce categories sync output."""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    def produce(self, result: ResultEnvelope[OutlookCategoriesSyncResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to sync categories.')}")
            return

        payload = result.payload
        prefix = "Would sync" if self._dry_run else "Categories sync complete"
        print(f"{prefix}. Created: {payload.created}, Skipped: {payload.skipped}")


class OutlookFoldersSyncProducer(Producer[ResultEnvelope[OutlookFoldersSyncResult]]):
    """Produce folders sync output."""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    def produce(self, result: ResultEnvelope[OutlookFoldersSyncResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to sync folders.')}")
            return

        payload = result.payload
        prefix = "Would sync" if self._dry_run else "Folders sync complete"
        print(f"{prefix}. Created: {payload.created}, Skipped: {payload.skipped}")


class OutlookCalendarAddProducer(Producer[ResultEnvelope[OutlookCalendarAddResult]]):
    """Produce calendar add output."""

    def produce(self, result: ResultEnvelope[OutlookCalendarAddResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Failed to create event: {diag.get('error', 'unknown error')}")
            return

        print(f"Created event: {result.payload.event_id} subject={result.payload.subject}")


class OutlookCalendarAddRecurringProducer(Producer[ResultEnvelope[OutlookCalendarAddRecurringResult]]):
    """Produce calendar add recurring output."""

    def produce(self, result: ResultEnvelope[OutlookCalendarAddRecurringResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Failed to create recurring event: {diag.get('error', 'unknown error')}")
            return

        print(f"Created recurring series: {result.payload.event_id} subject={result.payload.subject}")


class OutlookCalendarAddFromConfigProducer(Producer[ResultEnvelope[OutlookCalendarAddFromConfigResult]]):
    """Produce calendar add from config output."""

    def produce(self, result: ResultEnvelope[OutlookCalendarAddFromConfigResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to add events from config.')}")
            return

        print(f"Created {result.payload.created} events/series from config")
