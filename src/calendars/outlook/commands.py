"""Outlook calendar command implementations."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.auth import build_outlook_service_from_args
from core.date_utils import DAY_MAP
from core.pipeline import BaseProducer, SafeProcessor, run_pipeline
from ..outlook_service import EventCreationParams, RecurringEventCreationParams

from ..outlook_pipelines import (
    OutlookAddProcessor,
    OutlookAddProducer,
    OutlookAddRequest,
    OutlookAddEventProcessor,
    OutlookAddEventProducer,
    OutlookAddEventRequest,
    OutlookAddRecurringProcessor,
    OutlookAddRecurringProducer,
    OutlookAddRecurringRequest,
    OutlookDedupProcessor,
    OutlookDedupProducer,
    OutlookDedupRequest,
    OutlookRemoveProcessor,
    OutlookRemoveProducer,
    OutlookRemoveRequest,
    OutlookRemindersProcessor,
    OutlookRemindersProducer,
    OutlookRemindersRequest,
    OutlookSettingsProcessor,
    OutlookSettingsProducer,
    OutlookSettingsRequest,
    OutlookScheduleImportProcessor,
    OutlookScheduleImportProducer,
    OutlookScheduleImportRequest,
    OutlookListOneOffsProcessor,
    OutlookListOneOffsProducer,
    OutlookListOneOffsRequest,
    OutlookCalendarShareProcessor,
    OutlookCalendarShareProducer,
    OutlookCalendarShareRequest,
    OutlookLocationsApplyProcessor,
    OutlookLocationsProducer,
    OutlookLocationsRequest,
    OutlookLocationsUpdateProcessor,
    OutlookLocationsEnrichProcessor,
    OutlookLocationsEnrichProducer,
    OutlookLocationsEnrichRequest,
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookVerifyRequest,
    OutlookMailListProcessor,
    OutlookMailListProducer,
    OutlookMailListRequest,
    IcsDraftProcessor,
    IcsDraftProducer,
    IcsDraftRequest,
)
from ..scan_common import (
    RANGE_PAT,
    html_to_text,
    norm_time,
    infer_meta_from_text,
)


def _build_outlook_service(args: argparse.Namespace):
    """Create an OutlookService using shared resolver; returns None on failure."""
    try:
        return build_outlook_service_from_args(args)
    except Exception as exc:
        print(str(exc))
        return None


def run_outlook_mail_list(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookMailListRequest(
        service=svc,
        folder=getattr(args, "folder", "inbox"),
        top=int(getattr(args, "top", 5)),
        pages=int(getattr(args, "pages", 1)),
    )
    return run_pipeline(request, OutlookMailListProcessor, OutlookMailListProducer)


def run_outlook_add(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    params = EventCreationParams(
        subject=args.subject,
        start_iso=args.start,
        end_iso=args.end,
        calendar_id=None,
        calendar_name=getattr(args, "calendar", None),
        tz=getattr(args, "tz", None),
        body_html=getattr(args, "body_html", None),
        all_day=bool(getattr(args, "all_day", False)),
        location=getattr(args, "location", None),
        no_reminder=bool(getattr(args, "no_reminder", False)),
        reminder_minutes=getattr(args, "reminder_minutes", None),
    )
    request = OutlookAddEventRequest(service=svc, params=params)
    return run_pipeline(request, OutlookAddEventProcessor, OutlookAddEventProducer)


def run_outlook_locations_enrich(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookLocationsEnrichRequest(
        service=svc,
        calendar=args.calendar,
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    return run_pipeline(request, OutlookLocationsEnrichProcessor, OutlookLocationsEnrichProducer)


def run_outlook_calendar_share(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookCalendarShareRequest(
        service=svc,
        calendar=args.calendar,
        recipient=getattr(args, "recipient", None),
        role=getattr(args, "role", "write"),
    )
    return run_pipeline(request, OutlookCalendarShareProcessor, OutlookCalendarShareProducer)


def run_outlook_schedule_import(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookScheduleImportRequest(
        source=args.source,
        kind=getattr(args, "kind", None),
        calendar=getattr(args, "calendar", None),
        tz=getattr(args, "tz", None),
        until=getattr(args, "until", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        no_reminder=bool(getattr(args, "no_reminder", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookScheduleImportProcessor, OutlookScheduleImportProducer)


def run_outlook_add_recurring(args: argparse.Namespace) -> int:
    if not (args.until or args.count):
        print("Provide either --until (YYYY-MM-DD) or --count for the recurrence range")
        return 2
    if args.repeat == "weekly" and not args.byday:
        print("For weekly recurrence, provide --byday like MO,WE,FR")
        return 2
    byday = None
    if getattr(args, "byday", None):
        byday = [s.strip() for s in str(args.byday).split(",") if s.strip()]
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    params = RecurringEventCreationParams(
        subject=args.subject,
        start_time=args.start_time,
        end_time=args.end_time,
        repeat=args.repeat,
        calendar_id=None,
        calendar_name=getattr(args, "calendar", None),
        tz=getattr(args, "tz", None),
        interval=int(getattr(args, "interval", 1) or 1),
        byday=byday,
        range_start_date=args.range_start,
        range_until=getattr(args, "until", None),
        count=getattr(args, "count", None),
        body_html=getattr(args, "body_html", None),
        location=getattr(args, "location", None),
        exdates=[s.strip() for s in str(getattr(args, "exdates", "") or "").split(",") if s.strip()] or None,
        no_reminder=bool(getattr(args, "no_reminder", False)),
        reminder_minutes=getattr(args, "reminder_minutes", None),
    )
    request = OutlookAddRecurringRequest(service=svc, params=params)
    return run_pipeline(request, OutlookAddRecurringProcessor, OutlookAddRecurringProducer)


def run_outlook_add_from_config(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookAddRequest(
        config_path=Path(args.config),
        dry_run=bool(getattr(args, "dry_run", False)),
        force_no_reminder=bool(getattr(args, "no_reminder", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookAddProcessor, OutlookAddProducer)


def run_outlook_verify_from_config(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookVerifyRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        service=svc,
    )
    return run_pipeline(request, OutlookVerifyProcessor, OutlookVerifyProducer)


def run_outlook_update_locations(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookLocationsRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookLocationsUpdateProcessor, OutlookLocationsProducer)


def run_outlook_apply_locations(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookLocationsRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        all_occurrences=bool(getattr(args, "all_occurrences", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookLocationsApplyProcessor, OutlookLocationsProducer)


def run_outlook_reminders_off(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookRemindersRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        all_occurrences=bool(getattr(args, "all_occurrences", False)),
        set_off=True,
        minutes=None,
    )
    return run_pipeline(request, OutlookRemindersProcessor, OutlookRemindersProducer)


def run_outlook_list_one_offs(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookListOneOffsRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        limit=int(getattr(args, "limit", 200) or 200),
        out_path=Path(getattr(args, "out")) if getattr(args, "out", None) else None,
    )
    return run_pipeline(request, OutlookListOneOffsProcessor, OutlookListOneOffsProducer)


def run_outlook_reminders_set(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    minutes = getattr(args, "minutes", None)
    if not getattr(args, "off", False) and minutes is None:
        print("--minutes is required unless --off is set.")
        return 2
    request = OutlookRemindersRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        all_occurrences=False,
        set_off=bool(getattr(args, "off", False)),
        minutes=None if getattr(args, "off", False) else int(minutes),
    )
    return run_pipeline(request, OutlookRemindersProcessor, OutlookRemindersProducer)


def run_outlook_settings_apply(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookSettingsRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookSettingsProcessor, OutlookSettingsProducer)


def run_outlook_dedup(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookDedupRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        apply=bool(getattr(args, "apply", False)),
        keep_newest=bool(getattr(args, "keep_newest", False)),
        prefer_delete_nonstandard=bool(getattr(args, "prefer_delete_nonstandard", False)),
        delete_standardized=bool(getattr(args, "delete_standardized", False)),
    )
    return run_pipeline(request, OutlookDedupProcessor, OutlookDedupProducer)


def run_outlook_remove_from_config(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookRemoveRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        subject_only=bool(getattr(args, "subject_only", False)),
        apply=bool(getattr(args, "apply", False)),
        service=svc,
    )
    return run_pipeline(request, OutlookRemoveProcessor, OutlookRemoveProducer)


def _scan_infer_meta(subj: str, text: str, recvd: str) -> dict:
    """Infer metadata from Outlook message fields."""
    from ..scan_common import MetaParserConfig

    config = MetaParserConfig(default_year=int((recvd or "")[:4] or 0))
    return infer_meta_from_text(f"{subj or ''}\n{text}", config=config)


def _scan_extract_from_message(msg: dict, calendar: str) -> list:
    """Extract schedule candidates from a single Outlook message."""
    subj = msg.get("subject") or ""
    recvd = msg.get("receivedDateTime") or ""
    frm = ((msg.get("from") or {}).get("emailAddress") or {}).get("address") or ""
    body = (msg.get("body") or {}).get("content") or msg.get("bodyPreview") or ""
    text = html_to_text(body)
    items = []
    for m in RANGE_PAT.finditer(text):
        day_raw = (m.group("day") or "").lower()
        byday = [DAY_MAP.get(day_raw, day_raw[:2].upper())]
        t1 = norm_time(m.group("h1"), m.group("m1"), m.group("ampm1"))
        t2 = norm_time(m.group("h2"), m.group("m2"), m.group("ampm2"))
        items.append({
            "source": {"id": msg.get("id", ""), "from": frm, "received": recvd, "subject": subj, "text": text},
            "event": {
                "calendar": calendar,
                "subject": subj or "Class",
                "repeat": "weekly",
                "byday": byday,
                "start_time": t1,
                "end_time": t2,
            },
        })
    return items


def _scan_enrich_items(extracted: list) -> None:
    """Enrich extracted events with metadata from their source messages."""
    for item in extracted:
        src = item["source"]
        meta = _scan_infer_meta(src.get("subject", ""), src.get("text") or "", src.get("received", ""))
        ev = item["event"]
        if meta.get("subject"):
            ev["subject"] = meta["subject"]
        if meta.get("location"):
            ev["location"] = meta["location"]
        if meta.get("range"):
            ev.setdefault("range", {}).update(meta["range"])  # type: ignore[call-arg]


def _scan_dedup_events(extracted: list) -> list:
    """Deduplicate extracted events by (subject, byday, start_time, end_time)."""
    seen: set = set()
    events = []
    for item in extracted:
        ev = item["event"]
        key = (ev.get("subject"), tuple(ev.get("byday") or []), ev.get("start_time"), ev.get("end_time"))
        if key not in seen:
            seen.add(key)
            events.append(ev)
    return events


@dataclass
class OutlookScanRequest:
    service: Any
    from_text: str
    days: int
    top: int
    pages: int
    calendar: str | None
    out: str | None


@dataclass
class OutlookScanResult:
    events: list[dict[str, Any]]
    message_count: int
    extracted: list[dict[str, Any]]
    out: str | None


class OutlookScanProcessor(SafeProcessor[OutlookScanRequest, OutlookScanResult]):
    def _process_safe(self, payload: OutlookScanRequest) -> OutlookScanResult:
        svc = payload.service
        query = f'from:"{payload.from_text}"'
        ids = svc.search_inbox_messages(query, days=payload.days, top=payload.top, pages=payload.pages)
        if not ids:
            return OutlookScanResult(events=[], message_count=0, extracted=[], out=payload.out)

        extracted: list[dict[str, Any]] = []
        for mid in ids:
            try:
                msg = svc.get_message(mid, select_body=True)
            except Exception as exc:  # nosec B112 - skip unreadable messages
                extracted.append({"_error": f"failed to fetch {mid}: {exc}"})
                continue
            extracted.extend(_scan_extract_from_message(msg, payload.calendar))

        _scan_enrich_items(extracted)
        events = _scan_dedup_events(extracted)
        return OutlookScanResult(
            events=events,
            message_count=len(ids),
            extracted=extracted[:10],
            out=payload.out,
        )


class OutlookScanProducer(BaseProducer):
    def _produce_success(self, payload: OutlookScanResult, diagnostics: dict[str, Any] | None) -> None:
        from core.yamlio import dump_config

        if not payload.events:
            if not payload.message_count:
                self._writer.print("No matching messages found.")
            else:
                self._writer.print("No schedule-like lines found in matching emails.")
            return

        self._writer.print(f"Found {len(payload.events)} candidate recurring class entries from {payload.message_count} messages.")
        if payload.out:
            dump_config(payload.out, {"events": payload.events, "_sources": payload.extracted})
            self._writer.print(f"Wrote plan to {payload.out}")
        else:
            for ev in payload.events:
                self._writer.print(
                    f"- {ev.get('subject')} {','.join(ev.get('byday') or [])} "
                    f"{ev.get('start_time')}-{ev.get('end_time')} "
                    f"calendar={ev.get('calendar') or '<default>'}"
                )
            self._writer.print("Use --out plan.yaml to write YAML.")


def run_outlook_scan_classes(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookScanRequest(
        service=svc,
        from_text=args.from_text,
        days=int(getattr(args, "days", 60)),
        top=int(getattr(args, "top", 25)),
        pages=int(getattr(args, "pages", 2)),
        calendar=getattr(args, "calendar", None),
        out=getattr(args, "out", None),
    )
    return run_pipeline(request, OutlookScanProcessor, OutlookScanProducer)


def run_outlook_ics_draft(args: argparse.Namespace) -> int:
    """Create a Gmail draft with a .ics attachment from a plan YAML file."""
    dry_run = bool(getattr(args, "dry_run", False))

    gmail_client = None
    if not dry_run:
        try:
            from core.auth import build_gmail_service_from_args
            gmail_client = build_gmail_service_from_args(args)
        except Exception as exc:
            print(f"Failed to build Gmail client: {exc}")
            return 1

    request = IcsDraftRequest(
        config_path=Path(args.config),
        recipient=args.recipient,
        subject=args.subject,
        dry_run=dry_run,
        gmail_client=gmail_client,
    )
    return run_pipeline(request, IcsDraftProcessor, IcsDraftProducer)
