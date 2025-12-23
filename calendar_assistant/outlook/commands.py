from __future__ import annotations

"""Outlook calendar command implementations."""

import argparse
from pathlib import Path

from core.auth import build_outlook_service_from_args

from ..outlook_pipelines import (
    OutlookAddProcessor,
    OutlookAddProducer,
    OutlookAddRequest,
    OutlookAddRequestConsumer,
    OutlookAddEventProcessor,
    OutlookAddEventProducer,
    OutlookAddEventRequest,
    OutlookAddEventRequestConsumer,
    OutlookAddRecurringProcessor,
    OutlookAddRecurringProducer,
    OutlookAddRecurringRequest,
    OutlookAddRecurringRequestConsumer,
    OutlookDedupProcessor,
    OutlookDedupProducer,
    OutlookDedupRequest,
    OutlookDedupRequestConsumer,
    OutlookRemoveProcessor,
    OutlookRemoveProducer,
    OutlookRemoveRequest,
    OutlookRemoveRequestConsumer,
    OutlookRemindersProcessor,
    OutlookRemindersProducer,
    OutlookRemindersRequest,
    OutlookRemindersRequestConsumer,
    OutlookSettingsProcessor,
    OutlookSettingsProducer,
    OutlookSettingsRequest,
    OutlookSettingsRequestConsumer,
    OutlookScheduleImportProcessor,
    OutlookScheduleImportProducer,
    OutlookScheduleImportRequest,
    OutlookScheduleImportRequestConsumer,
    OutlookListOneOffsProcessor,
    OutlookListOneOffsProducer,
    OutlookListOneOffsRequest,
    OutlookListOneOffsRequestConsumer,
    OutlookCalendarShareProcessor,
    OutlookCalendarShareProducer,
    OutlookCalendarShareRequest,
    OutlookCalendarShareRequestConsumer,
    OutlookLocationsApplyProcessor,
    OutlookLocationsProducer,
    OutlookLocationsRequest,
    OutlookLocationsRequestConsumer,
    OutlookLocationsUpdateProcessor,
    OutlookLocationsEnrichProcessor,
    OutlookLocationsEnrichProducer,
    OutlookLocationsEnrichRequest,
    OutlookLocationsEnrichRequestConsumer,
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
    OutlookMailListProcessor,
    OutlookMailListProducer,
    OutlookMailListRequest,
    OutlookMailListRequestConsumer,
)
from ..scan_common import (
    DAY_MAP,
    RANGE_PAT,
    CLASS_PAT,
    LOC_LABEL_PAT,
    FACILITIES,
    DATE_RANGE_PAT,
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
    envelope = OutlookMailListProcessor().process(OutlookMailListRequestConsumer(request).consume())
    OutlookMailListProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_outlook_add(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookAddEventRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        subject=args.subject,
        start_iso=args.start,
        end_iso=args.end,
        tz=getattr(args, "tz", None),
        body_html=getattr(args, "body_html", None),
        all_day=bool(getattr(args, "all_day", False)),
        location=getattr(args, "location", None),
        no_reminder=bool(getattr(args, "no_reminder", False)),
        reminder_minutes=getattr(args, "reminder_minutes", None),
    )
    envelope = OutlookAddEventProcessor().process(OutlookAddEventRequestConsumer(request).consume())
    OutlookAddEventProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookLocationsEnrichProcessor().process(OutlookLocationsEnrichRequestConsumer(request).consume())
    OutlookLocationsEnrichProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookCalendarShareProcessor().process(OutlookCalendarShareRequestConsumer(request).consume())
    OutlookCalendarShareProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookScheduleImportProcessor().process(OutlookScheduleImportRequestConsumer(request).consume())
    OutlookScheduleImportProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    request = OutlookAddRecurringRequest(
        service=svc,
        calendar=getattr(args, "calendar", None),
        subject=args.subject,
        start_time=args.start_time,
        end_time=args.end_time,
        tz=getattr(args, "tz", None),
        repeat=args.repeat,
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
    envelope = OutlookAddRecurringProcessor().process(OutlookAddRecurringRequestConsumer(request).consume())
    OutlookAddRecurringProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookAddProcessor().process(OutlookAddRequestConsumer(request).consume())
    OutlookAddProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_outlook_verify_from_config(args: argparse.Namespace) -> int:
    svc = _build_outlook_service(args)
    if not svc:
        return 1
    request = OutlookVerifyRequest(
        config_path=Path(args.config),
        calendar=getattr(args, "calendar", None),
        service=svc,
    )
    envelope = OutlookVerifyProcessor().process(OutlookVerifyRequestConsumer(request).consume())
    OutlookVerifyProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookLocationsUpdateProcessor().process(OutlookLocationsRequestConsumer(request).consume())
    OutlookLocationsProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookLocationsApplyProcessor().process(OutlookLocationsRequestConsumer(request).consume())
    OutlookLocationsProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookRemindersProcessor().process(OutlookRemindersRequestConsumer(request).consume())
    OutlookRemindersProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookListOneOffsProcessor().process(OutlookListOneOffsRequestConsumer(request).consume())
    OutlookListOneOffsProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookRemindersProcessor().process(OutlookRemindersRequestConsumer(request).consume())
    OutlookRemindersProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(request).consume())
    OutlookSettingsProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookDedupProcessor().process(OutlookDedupRequestConsumer(request).consume())
    OutlookDedupProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = OutlookRemoveProcessor().process(OutlookRemoveRequestConsumer(request).consume())
    OutlookRemoveProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_outlook_scan_classes(args: argparse.Namespace) -> int:
    from ..yamlio import dump_config

    svc = _build_outlook_service(args)
    if not svc:
        return 1

    query = f"from:\"{args.from_text}\""
    ids = svc.search_inbox_messages(query, days=getattr(args, 'days', 60), top=getattr(args, 'top', 25), pages=getattr(args, 'pages', 2))
    if not ids:
        print("No matching messages found.")
        return 0

    def infer_meta(subj: str, text: str, recvd: str) -> dict:
        meta = infer_meta_from_text(
            f"{subj or ''}\n{text}",
            facilities=FACILITIES,
            date_range_pat=DATE_RANGE_PAT,
            class_pat=CLASS_PAT,
            loc_label_pat=LOC_LABEL_PAT,
            default_year=int((recvd or "")[:4] or 0),
        )
        if meta.get("subject"):
            meta["subject"] = meta["subject"].replace("Swim Kids", "Swim Kids").replace("Swimmer ", "Swimmer ")
        return meta

    extracted = []
    for mid in ids:
        try:
            msg = svc.get_message(mid, select_body=True)
        except Exception as e:
            print(f"Warning: failed to fetch message {mid}: {e}")
            continue
        subj = msg.get("subject") or ""
        recvd = msg.get("receivedDateTime") or ""
        frm = ((msg.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        body = (msg.get("body") or {}).get("content") or msg.get("bodyPreview") or ""
        text = html_to_text(body)
        # Look for day + time ranges
        matches = list(RANGE_PAT.finditer(text))
        for m in matches:
            day_raw = (m.group("day") or "").lower()
            byday = [DAY_MAP.get(day_raw, day_raw[:2].upper())]
            t1 = norm_time(m.group("h1"), m.group("m1"), m.group("ampm1"))
            t2 = norm_time(m.group("h2"), m.group("m2"), m.group("ampm2"))
            extracted.append({
                "source": {"id": mid, "from": frm, "received": recvd, "subject": subj, "text": text},
                "event": {
                    "calendar": getattr(args, "calendar", None),
                    "subject": subj or "Class",
                    "repeat": "weekly",
                    "byday": byday,
                    "start_time": t1,
                    "end_time": t2,
                },
            })

    if not extracted:
        print("No schedule-like lines found in matching emails.")
        return 0

    # Enrich from subject/body
    for item in extracted:
        src = item["source"]
        meta = infer_meta(
            src.get("subject"),
            src.get("text") or "",
            src.get("received"),
        )
        ev = item["event"]
        if meta.get("subject"):
            ev["subject"] = meta["subject"]
        if meta.get("location"):
            ev["location"] = meta["location"]
        if meta.get("range"):
            ev.setdefault("range", {}).update(meta["range"])  # type: ignore[call-arg]

    # Collapse into plan (events: []) with dedup on (subject, byday, start_time, end_time)
    seen = set()
    events = []
    for item in extracted:
        ev = item["event"]
        key = (ev.get("subject"), tuple(ev.get("byday") or []), ev.get("start_time"), ev.get("end_time"))
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)

    print(f"Found {len(events)} candidate recurring class entries from {len(ids)} messages.")
    if args.out:
        outp = args.out
        data = {"events": events, "_sources": extracted[:10]}
        dump_config(outp, data)
        print(f"Wrote plan to {outp}")
    else:
        # Preview
        for ev in events:
            print(f"- {ev.get('subject')} {','.join(ev.get('byday') or [])} {ev.get('start_time')}-{ev.get('end_time')} calendar={ev.get('calendar') or '<default>'}")
        print("Use --out plan.yaml to write YAML.")
    return 0
