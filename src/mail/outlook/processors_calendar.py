"""Processors for Outlook categories, folders, and calendar pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.outlook.models import EventCreationParams, RecurringEventCreationParams
from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    OutlookCategoriesListPayload,
    OutlookCategoriesExportPayload,
    OutlookCategoriesSyncPayload,
    OutlookFoldersSyncPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookCalendarAddFromConfigPayload,
)


# Result dataclasses

@dataclass
class OutlookCategoriesListResult:
    """Result of categories list."""
    categories: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OutlookCategoriesExportResult:
    """Result of categories export."""
    count: int = 0
    out_path: str = ""


@dataclass
class OutlookCategoriesSyncResult:
    """Result of categories sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookFoldersSyncResult:
    """Result of folders sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookCalendarAddResult:
    """Result of calendar add."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddRecurringResult:
    """Result of calendar add recurring."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddFromConfigResult:
    """Result of calendar add from config."""
    created: int = 0


def _entry_name(entry) -> str | None:
    """Extract the name from a label entry (dict or str)."""
    if isinstance(entry, dict):
        return entry.get("name")
    if isinstance(entry, str):
        return entry
    return None


class OutlookCategoriesListProcessor(Processor[OutlookCategoriesListPayload, ResultEnvelope[OutlookCategoriesListResult]]):
    """List Outlook categories."""

    def process(self, payload: OutlookCategoriesListPayload) -> ResultEnvelope[OutlookCategoriesListResult]:
        try:
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesListResult(categories=cats),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesExportProcessor(Processor[OutlookCategoriesExportPayload, ResultEnvelope[OutlookCategoriesExportResult]]):
    """Export Outlook categories to YAML."""

    def process(self, payload: OutlookCategoriesExportPayload) -> ResultEnvelope[OutlookCategoriesExportResult]:
        try:
            from pathlib import Path
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            labels = []
            for c in cats:
                entry = {"name": c.get("name", "")}
                col = c.get("color")
                if isinstance(col, dict) and col.get("name"):
                    entry["color"] = {"name": col.get("name")}
                labels.append(entry)

            data = {"labels": labels}
            outp = Path(payload.out_path)
            outp.parent.mkdir(parents=True, exist_ok=True)
            from ..yamlio import dump_config
            dump_config(str(outp), data)

            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesExportResult(count=len(labels), out_path=str(outp)),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesSyncProcessor(Processor[OutlookCategoriesSyncPayload, ResultEnvelope[OutlookCategoriesSyncResult]]):
    """Sync Outlook categories from YAML config."""

    def process(self, payload: OutlookCategoriesSyncPayload) -> ResultEnvelope[OutlookCategoriesSyncResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_labels_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []
            if not isinstance(labels, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
                )

            desired = normalize_labels_for_outlook(labels)
            existing = {c.get("name"): c for c in client.list_labels()}
            created, skipped = self._sync_categories(client, desired, existing, payload.dry_run)
            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _create_one_category(self, client, entry, dry_run: bool) -> bool:
        """Create a single category; return True if created."""
        if dry_run:
            return True
        try:
            color = entry.get("color") if isinstance(entry, dict) else None
            client.create_label(entry if isinstance(entry, str) else entry.get("name"), color=color)
            return True
        except Exception:  # nosec B110 - category creation failure
            return False

    def _sync_categories(self, client, desired: list, existing: dict, dry_run: bool):
        """Sync category entries; return (created, skipped)."""
        created = skipped = 0
        for entry in desired:
            name = entry.get("name") if isinstance(entry, dict) else entry
            if not name:
                continue
            if name in existing:
                skipped += 1
                continue
            if self._create_one_category(client, entry, dry_run):
                created += 1
        return created, skipped


class OutlookFoldersSyncProcessor(Processor[OutlookFoldersSyncPayload, ResultEnvelope[OutlookFoldersSyncResult]]):
    """Sync Outlook folders from YAML config."""

    def process(self, payload: OutlookFoldersSyncPayload) -> ResultEnvelope[OutlookFoldersSyncResult]:
        try:
            from ..yamlio import load_config

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []
            if not isinstance(labels, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
                )

            path_map = client.get_folder_path_map()
            created, skipped = self._sync_folders(client, labels, path_map, payload.dry_run)
            return ResultEnvelope(
                status="success",
                payload=OutlookFoldersSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _sync_one_folder(self, client, name: str, path_map: dict, dry_run: bool) -> bool:
        """Ensure a single folder exists; return True if it counts as created.

        Under dry_run this returns True WITHOUT creating anything, so the
        caller's `created` tally reports what a real run would create. That is
        the point of the plan output, and it matches the pre-refactor
        behavior exactly -- do not "fix" it to return False, which would make
        every dry-run plan report zero.
        """
        if dry_run:
            return True
        fid = client.ensure_folder_path(name)
        if not fid:
            return False
        path_map[name] = fid
        return True

    def _sync_folders(self, client, labels: list, path_map: dict, dry_run: bool):
        """Sync folder entries; return (created, skipped)."""
        created = skipped = 0
        for entry in labels:
            name = _entry_name(entry)
            if not name or str(name).startswith("["):
                skipped += 1 if name else 0
                continue
            if name in path_map:
                skipped += 1
                continue
            if self._sync_one_folder(client, name, path_map, dry_run):
                created += 1
        return created, skipped


class OutlookCalendarAddProcessor(Processor[OutlookCalendarAddPayload, ResultEnvelope[OutlookCalendarAddResult]]):
    """Add a calendar event."""

    def process(self, payload: OutlookCalendarAddPayload) -> ResultEnvelope[OutlookCalendarAddResult]:
        try:
            evt = payload.client.create_event(EventCreationParams(
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                tz=payload.tz,
                body_html=payload.body_html,
                all_day=payload.all_day,
                location=payload.location,
                no_reminder=payload.no_reminder,
            ))
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddRecurringProcessor(Processor[OutlookCalendarAddRecurringPayload, ResultEnvelope[OutlookCalendarAddRecurringResult]]):
    """Add a recurring calendar event."""

    def process(self, payload: OutlookCalendarAddRecurringPayload) -> ResultEnvelope[OutlookCalendarAddRecurringResult]:
        try:
            evt = payload.client.create_recurring_event(RecurringEventCreationParams(
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_time=payload.start_time,
                end_time=payload.end_time,
                tz=payload.tz,
                repeat=payload.repeat,
                interval=payload.interval,
                byday=payload.byday,
                range_start_date=payload.range_start,
                range_until=payload.until,
                count=payload.count,
                body_html=payload.body_html,
                location=payload.location,
                exdates=payload.exdates,
                no_reminder=payload.no_reminder,
            ))
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddRecurringResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddFromConfigProcessor(Processor[OutlookCalendarAddFromConfigPayload, ResultEnvelope[OutlookCalendarAddFromConfigResult]]):
    """Add calendar events from a config file."""

    def process(self, payload: OutlookCalendarAddFromConfigPayload) -> ResultEnvelope[OutlookCalendarAddFromConfigResult]:
        try:
            from ..yamlio import load_config

            cfg = load_config(payload.config_path)
            items = cfg.get("events") if isinstance(cfg, dict) else None
            if not isinstance(items, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Config must contain events: [] list", "code": 2},
                )

            created = self._create_events_from_config(items, payload.client, payload.no_reminder)

            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddFromConfigResult(created=created),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _create_one_event_from_config(self, ev: dict, client: Any, no_reminder: bool) -> bool:
        """Create one event (recurring or single) from a config entry."""
        if not isinstance(ev, dict) or not ev.get("subject"):
            return False
        if ev.get("repeat"):
            return self._create_recurring_event(ev, client, no_reminder)
        return self._create_single_event(ev, client, no_reminder)

    def _create_events_from_config(
        self, events: list[dict[str, Any]], client: Any, no_reminder: bool
    ) -> int:
        """Create events from config list."""
        return sum(
            1 for ev in events
            if self._create_one_event_from_config(ev, client, no_reminder)
        )

    @staticmethod
    def _first_present(ev: dict[str, Any], *keys: str, default: Any = None) -> Any:
        """Return the first non-falsy value among aliased config keys."""
        for key in keys:
            val = ev.get(key)
            if val:
                return val
        return default

    def _build_recurring_event_range(self, ev: dict[str, Any]) -> tuple[str, Any]:
        """Resolve (range_start_date, range_until), preferring the nested ``range`` block."""
        rng = ev.get("range") or {}
        start_date = rng.get("start_date") or self._first_present(ev, "start_date", "startDate", default="")
        until = rng.get("until") or ev.get("until")
        return start_date, until

    def _build_recurring_event_params(
        self, ev: dict[str, Any], no_reminder: bool
    ) -> RecurringEventCreationParams:
        """Map a config dict (with legacy key aliases) into recurrence creation params."""
        range_start_date, range_until = self._build_recurring_event_range(ev)
        return RecurringEventCreationParams(
            calendar_name=ev.get("calendar"),
            subject=ev.get("subject") or "",
            start_time=self._first_present(ev, "start_time", "startTime", "start-time", default=""),
            end_time=self._first_present(ev, "end_time", "endTime", "end-time", default=""),
            tz=ev.get("tz"),
            repeat=ev.get("repeat") or "",
            interval=int(ev.get("interval", 1)),
            byday=self._first_present(ev, "byday", "byDay"),
            range_start_date=range_start_date,
            range_until=range_until,
            count=ev.get("count"),
            body_html=self._first_present(ev, "body_html", "bodyHtml"),
            location=ev.get("location"),
            exdates=self._first_present(ev, "exdates", "exceptions", default=[]),
            no_reminder=no_reminder,
        )

    def _create_recurring_event(self, ev: dict[str, Any], client: Any, no_reminder: bool) -> bool:
        """Create a recurring event from config dict."""
        try:
            client.create_recurring_event(self._build_recurring_event_params(ev, no_reminder))
            return True
        except Exception:  # nosec B110 - recurring event creation failure
            return False

    def _create_single_event(self, ev: dict[str, Any], client: Any, no_reminder: bool) -> bool:
        """Create a single event from config dict."""
        start_iso = ev.get("start")
        end_iso = ev.get("end")
        if not (start_iso and end_iso):
            return False

        try:
            client.create_event(EventCreationParams(
                calendar_name=ev.get("calendar"),
                subject=ev.get("subject") or "",
                start_iso=start_iso,
                end_iso=end_iso,
                tz=ev.get("tz"),
                body_html=ev.get("body_html") or ev.get("bodyHtml"),
                all_day=bool(ev.get("all_day") or ev.get("allDay")),
                location=ev.get("location"),
                no_reminder=no_reminder,
            ))
            return True
        except Exception:  # nosec B110 - event creation failure
            return False
