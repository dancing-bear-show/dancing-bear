"""Calendar Assistant CLI entrypoint.

Wires the public CLI and delegates to focused command handlers. Small OO
helpers (e.g., OutlookContext) centralize configuration to reduce duplication
without changing flags or subcommands.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional

from personal_core.assistant import BaseAssistant
from personal_core.auth import build_outlook_service

from .helpers import build_gmail_service_from_args as _build_gmail_service_raw
from .scan_common import (
    DAY_MAP,
    RANGE_PAT,
    CLASS_PAT,
    LOC_LABEL_PAT,
    FACILITIES,
    MONTH_MAP,
    DATE_RANGE_PAT,
    html_to_text,
    norm_time,
    infer_meta_from_text,
)
from .pipeline import (
    GmailAuth,
    GmailPlanProducer,
    GmailReceiptsProcessor,
    GmailReceiptsRequest,
    GmailReceiptsRequestConsumer,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailMailListProcessor,
    GmailMailListProducer,
    GmailMailListRequest,
    GmailMailListRequestConsumer,
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
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
)


def _build_gmail_service(args: argparse.Namespace):
    """Create an authenticated GmailService via shared auth helpers."""
    try:
        return _build_gmail_service_raw(args)
    except Exception as exc:
        print(f"Gmail auth error: {exc}")
        return None

assistant = BaseAssistant(
    "calendar_assistant",
    "agentic: calendar_assistant\npurpose: Outlook calendars + Gmail scans → plans",
)


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "Common subcommands:\n"
        "  outlook add|add-recurring|add-from-config|verify-from-config|update-locations|apply-locations|dedup|list-one-offs|schedule-import|calendar-share\n"
        "  gmail scan-classes|scan-receipts|scan-activerh\n"
    )
    p = argparse.ArgumentParser(description="Calendar Assistant CLI", epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    assistant.add_agentic_flags(p)
    p.add_argument("--profile", help="Credentials profile (INI section suffix, e.g., outlook_personal)")
    sub = p.add_subparsers(dest="command")

    p_outlook = sub.add_parser("outlook", help="Outlook calendar operations")
    sub_out = p_outlook.add_subparsers(dest="outlook_cmd")

    p_gmail = sub.add_parser("gmail", help="Gmail scan helpers for calendar")
    sub_g = p_gmail.add_subparsers(dest="gmail_cmd")
    p_g_scan = sub_g.add_parser("scan-classes", help="Scan recent Gmail for class schedules and output a plan")
    _add_common_gmail_auth_args(p_g_scan)
    p_g_scan.add_argument("--from-text", dest="from_text", default="active rh", help="Text to match sender (Gmail query)")
    p_g_scan.add_argument("--query", help="Raw Gmail query to use instead of --from-text/--days")
    _add_common_gmail_paging_args(p_g_scan, default_days=60, default_pages=5, default_page_size=100)
    p_g_scan.add_argument("--inbox-only", action="store_true", help="Restrict to Inbox (adds in:inbox)")
    p_g_scan.add_argument("--out", help="Optional output YAML plan path (events: [])")
    p_g_scan.add_argument("--calendar", help="Default calendar name to include in plan entries")
    p_g_scan.set_defaults(func=_cmd_gmail_scan_classes)

    p_g_rcpts = sub_g.add_parser("scan-receipts", help="Scan Gmail receipts (ActiveRH) and extract recurring events")
    _add_common_gmail_auth_args(p_g_rcpts)
    p_g_rcpts.add_argument("--from-text", dest="from_text", default="richmondhill.ca", help="Sender filter (Gmail query)")
    p_g_rcpts.add_argument("--query", help="Raw Gmail query to use instead of --from-text/--days")
    _add_common_gmail_paging_args(p_g_rcpts, default_days=365, default_pages=5, default_page_size=100)
    p_g_rcpts.add_argument("--out", required=True, help="Output YAML plan path (events: [])")
    p_g_rcpts.add_argument("--calendar", help="Default calendar name to include in plan entries")
    p_g_rcpts.set_defaults(func=_cmd_gmail_scan_receipts)

    # scan-activerh: generic targeting for Active RH receipts across programs
    p_g_arh = sub_g.add_parser("scan-activerh", help="Generic scan for ActiveRH receipts across programs")
    _add_common_gmail_auth_args(p_g_arh)
    p_g_arh.add_argument("--query", help="Raw Gmail query (overrides defaults)")
    _add_common_gmail_paging_args(p_g_arh, default_days=365, default_pages=10, default_page_size=100)
    p_g_arh.add_argument("--out", required=True, help="Output YAML plan path (events: [])")
    p_g_arh.add_argument("--calendar", help="Default calendar name to include in plan entries")
    p_g_arh.set_defaults(func=_cmd_gmail_scan_activerh)

    # gmail mail-list (read-only sniff test)
    p_g_list = sub_g.add_parser("mail-list", help="List recent Gmail messages (read-only)")
    _add_common_gmail_auth_args(p_g_list)
    p_g_list.add_argument("--from-text", dest="from_text", help="Optional sender filter (adds from:")
    p_g_list.add_argument("--query", help="Raw Gmail query; overrides defaults")
    _add_common_gmail_paging_args(p_g_list, default_days=7, default_pages=1, default_page_size=10)
    p_g_list.add_argument("--inbox-only", action="store_true", help="Restrict to Inbox (adds in:inbox)")
    p_g_list.set_defaults(func=_cmd_gmail_mail_list)

    # gmail sweep-top: find frequent senders in Inbox window
    p_g_sweep = sub_g.add_parser("sweep-top", help="Find top frequent senders in Inbox over a window")
    _add_common_gmail_auth_args(p_g_sweep)
    p_g_sweep.add_argument("--days", type=int, default=10, help="Look back N days (default 10)")
    p_g_sweep.add_argument("--pages", type=int, default=5, help="Max pages to fetch (default 5)")
    p_g_sweep.add_argument("--page-size", type=int, default=100, help="Page size (default 100)")
    p_g_sweep.add_argument("--top", type=int, default=10, help="How many top senders to show (default 10)")
    p_g_sweep.add_argument("--inbox-only", action="store_true", help="Restrict to Inbox (adds in:inbox)")
    p_g_sweep.add_argument("--out", help="Optional suggested Gmail filters YAML path")
    p_g_sweep.set_defaults(func=_cmd_gmail_sweep_top)

    p_add = sub_out.add_parser("add", help="Add a one-time event to a calendar")
    _add_common_outlook_args(p_add)
    p_add.add_argument("--calendar", help="Calendar name (e.g., Family). Defaults to primary if omitted")
    p_add.add_argument("--subject", required=True, help="Event subject/title")
    p_add.add_argument("--start", required=True, help="Start datetime ISO (YYYY-MM-DDTHH:MM[:SS])")
    p_add.add_argument("--end", required=True, help="End datetime ISO (YYYY-MM-DDTHH:MM[:SS])")
    p_add.add_argument("--tz", help="Time zone (IANA or Windows). Defaults to mailbox setting or UTC")
    p_add.add_argument("--location", help="Location display name")
    p_add.add_argument("--body-html", dest="body_html", help="HTML body content")
    p_add.add_argument("--all-day", action="store_true", help="Mark as all-day (expects date-only start/end)")
    p_add.add_argument("--no-reminder", action="store_true", help="Create event without reminders/alerts")
    p_add.add_argument("--reminder-minutes", type=int, help="Reminder minutes before start (enables reminder)")
    p_add.set_defaults(func=_cmd_outlook_add)

    p_rec = sub_out.add_parser("add-recurring", help="Add a recurring event with optional exclusions")
    _add_common_outlook_args(p_rec)
    p_rec.add_argument("--calendar", help="Calendar name (e.g., Family). Defaults to primary if omitted")
    p_rec.add_argument("--subject", required=True)
    p_rec.add_argument("--repeat", required=True, choices=["daily", "weekly", "monthly"], help="Recurrence type")
    p_rec.add_argument("--interval", type=int, default=1, help="Recurrence interval (default 1)")
    p_rec.add_argument("--byday", help="Days for weekly, comma-separated (e.g., MO,WE,FR)")
    p_rec.add_argument("--range-start", required=True, dest="range_start", help="Start date YYYY-MM-DD for the series")
    p_rec.add_argument("--until", help="End date YYYY-MM-DD for the series")
    p_rec.add_argument("--count", type=int, help="Occurrences count (alternative to --until)")
    p_rec.add_argument("--start-time", required=True, help="Start time HH:MM[:SS]")
    p_rec.add_argument("--end-time", required=True, help="End time HH:MM[:SS]")
    p_rec.add_argument("--tz", help="Time zone (IANA or Windows). Defaults to mailbox setting or UTC")
    p_rec.add_argument("--location", help="Location display name")
    p_rec.add_argument("--body-html", dest="body_html", help="HTML body content")
    p_rec.add_argument("--exdates", help="Comma-separated YYYY-MM-DD dates to exclude")
    p_rec.add_argument("--no-reminder", action="store_true", help="Create series without reminders/alerts")
    p_rec.add_argument("--reminder-minutes", type=int, help="Reminder minutes before start (enables reminder)")
    p_rec.set_defaults(func=_cmd_outlook_add_recurring)

    p_cfg = sub_out.add_parser("add-from-config", help="Add events defined in a YAML file")
    _add_common_outlook_args(p_cfg)
    p_cfg.add_argument("--config", required=True, help="YAML with events: [] entries")
    p_cfg.add_argument("--dry-run", action="store_true", help="Print actions without creating events")
    p_cfg.add_argument("--no-reminder", action="store_true", help="Create events without reminders/alerts")
    p_cfg.set_defaults(func=_cmd_outlook_add_from_config)

    # verify-from-config: check for duplicates in Outlook before create
    p_verify = sub_out.add_parser("verify-from-config", help="Verify plan against Outlook to avoid duplicates")
    _add_common_outlook_args(p_verify)
    p_verify.add_argument("--config", required=True, help="YAML with events: [] entries")
    p_verify.add_argument("--calendar", help="Calendar name (defaults to event.calendar or primary)")
    p_verify.set_defaults(func=_cmd_outlook_verify_from_config)

    # update-locations: pull current event locations from Outlook and update YAML
    p_update_loc = sub_out.add_parser("update-locations", help="Update YAML event locations from Outlook calendar")
    _add_common_outlook_args(p_update_loc)
    p_update_loc.add_argument("--config", required=True, help="YAML with events: [] entries")
    p_update_loc.add_argument("--calendar", help="Calendar name (defaults to event.calendar or primary)")
    p_update_loc.add_argument("--dry-run", action="store_true", help="Preview updates without writing")
    p_update_loc.set_defaults(func=_cmd_outlook_update_locations_from_config)

    # apply-locations: push YAML locations into Outlook events (patch locations)
    p_apply_loc = sub_out.add_parser("apply-locations", help="Apply locations from YAML to Outlook events")
    _add_common_outlook_args(p_apply_loc)
    p_apply_loc.add_argument("--config", required=True, help="YAML events config path")
    p_apply_loc.add_argument("--calendar", help="Calendar name (defaults to event.calendar or primary)")
    p_apply_loc.add_argument("--dry-run", action="store_true", help="Preview updates without patching events")
    p_apply_loc.add_argument("--all-occurrences", action="store_true", help="Update all matching events in window (dedup by series)")
    p_apply_loc.set_defaults(func=_cmd_outlook_apply_locations_from_config)

    # locations-enrich: update matching series with standardized locations
    p_enrich_loc = sub_out.add_parser("locations-enrich", help="Enrich Outlook event locations with full addresses")
    _add_common_outlook_args(p_enrich_loc)
    p_enrich_loc.add_argument("--calendar", required=True, help="Calendar name to scan/update")
    p_enrich_loc.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD")
    p_enrich_loc.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD")
    p_enrich_loc.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    p_enrich_loc.set_defaults(func=_cmd_outlook_locations_enrich)

    # list one-off events in a time window
    p_list_one = sub_out.add_parser("list-one-offs", help="List non-recurring (single) events in a calendar window")
    _add_common_outlook_args(p_list_one)
    p_list_one.add_argument("--calendar", help="Calendar name (e.g., 'Your Family')")
    p_list_one.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD (default: 30 days ago)")
    p_list_one.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD (default: 180 days ahead)")
    p_list_one.add_argument("--limit", type=int, default=200, help="How many rows to show (default 200)")
    p_list_one.add_argument("--out", help="Optional YAML output path (events: [])")
    p_list_one.set_defaults(func=_cmd_outlook_list_one_offs)

    # remove-from-config: delete events/series that match the YAML config
    p_rm_cfg = sub_out.add_parser("remove-from-config", help="Delete Outlook events/series matching a YAML config")
    _add_common_outlook_args(p_rm_cfg)
    p_rm_cfg.add_argument("--config", required=True, help="YAML with events: [] entries")
    p_rm_cfg.add_argument("--calendar", help="Calendar name (defaults to event.calendar or primary)")
    p_rm_cfg.add_argument("--apply", action="store_true", help="Actually delete; otherwise just plan")
    p_rm_cfg.add_argument("--subject-only", action="store_true", help="Match by subject only (ignore day/time)")
    p_rm_cfg.set_defaults(func=_cmd_outlook_remove_from_config)

    # dedup duplicates (same subject/day/time) across different series
    p_dedup = sub_out.add_parser("dedup", help="Find and optionally remove duplicate series by subject/day/time")
    _add_common_outlook_args(p_dedup)
    p_dedup.add_argument("--calendar", help="Calendar name (e.g., 'Your Family')")
    p_dedup.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD (default: 30 days ago)")
    p_dedup.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD (default: 180 days ahead)")
    p_dedup.add_argument("--apply", action="store_true", help="Delete duplicates (keep oldest series by default)")
    p_dedup.add_argument("--delete-standardized", action="store_true", help="Prefer deleting series whose location looks standardized (address-style)")
    p_dedup.add_argument("--keep-newest", action="store_true", help="Keep newest series (default keeps oldest)")
    p_dedup.add_argument("--prefer-delete-nonstandard", action="store_true", help="Prefer deleting series with non-standard location (missing/empty)")
    p_dedup.set_defaults(func=_cmd_outlook_dedup)

    p_scan = sub_out.add_parser("scan-classes", help="Scan recent emails for class schedules and output a plan")
    _add_common_outlook_args(p_scan)
    p_scan.add_argument("--from-text", dest="from_text", default="active rh", help="Text to match sender (used in $search)")
    p_scan.add_argument("--days", type=int, default=60, help="Look back N days (default 60)")
    p_scan.add_argument("--top", type=int, default=25, help="Items per page (default 25)")
    p_scan.add_argument("--pages", type=int, default=2, help="Max pages to fetch (default 2)")
    p_scan.add_argument("--out", help="Optional output YAML plan path (events: [])")
    p_scan.add_argument("--calendar", help="Default calendar name to include in plan entries")
    p_scan.set_defaults(func=_cmd_outlook_scan_classes)

    # schedule-import: import CSV/XLSX/PDF/URL into a new calendar
    p_sched = sub_out.add_parser("schedule-import", help="Import schedule file/URL and create a calendar of events")
    _add_common_outlook_args(p_sched)
    p_sched.add_argument("--calendar", help="New or existing calendar name (default: Imported Schedules)")
    p_sched.add_argument("--source", required=True, help="Path or URL to schedule (csv/xlsx/pdf/website)")
    p_sched.add_argument("--kind", choices=["auto","csv","xlsx","pdf","website"], default="auto", help="Source type (default: auto)")
    p_sched.add_argument("--tz", help="Time zone for events (IANA/Windows). Defaults to mailbox")
    p_sched.add_argument("--until", help="Global end date YYYY-MM-DD for recurring series (overrides parsed range)")
    p_sched.add_argument("--dry-run", action="store_true", help="Preview creates without writing")
    p_sched.add_argument("--no-reminder", action="store_true", help="Create events without reminders/alerts")
    p_sched.set_defaults(func=_cmd_outlook_schedule_import)

    # reminders-off: disable reminders for events in a date window
    p_rem = sub_out.add_parser("reminders-off", help="Turn off reminders for events in a date window")
    _add_common_outlook_args(p_rem)
    p_rem.add_argument("--calendar", help="Calendar name to update (defaults to primary)")
    p_rem.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD (default: 30 days ago)")
    p_rem.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD (default: 180 days ahead)")
    p_rem.add_argument("--all-occurrences", action="store_true", help="Also update occurrences (not just series masters)")
    p_rem.add_argument("--dry-run", action="store_true", help="Preview changes without patching events")
    p_rem.set_defaults(func=_cmd_outlook_reminders_off)

    # calendar-share: share a calendar with a recipient
    p_share = sub_out.add_parser("calendar-share", help="Share a calendar with a recipient (set permission role)")
    _add_common_outlook_args(p_share)
    p_share.add_argument("--calendar", required=True, help="Calendar name (e.g., 'Activities')")
    p_share.add_argument("--with", dest="recipient", required=True, help="Email address to share with")
    p_share.add_argument("--role", default="write", help="Role: read|write|limitedRead|freeBusyRead|delegate… (default: write)")
    p_share.set_defaults(func=_cmd_outlook_calendar_share)

    # reminders-set: bulk toggle or set reminder minutes across a window
    p_rem = sub_out.add_parser("reminders-set", help="Set reminders on/off or minutes for events in a date window")
    _add_common_outlook_args(p_rem)
    p_rem.add_argument("--calendar", required=True, help="Calendar name to modify")
    p_rem.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD (default: 30 days ago)")
    p_rem.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD (default: 180 days ahead)")
    mode = p_rem.add_mutually_exclusive_group(required=True)
    mode.add_argument("--off", action="store_true", help="Turn reminders off for matching events")
    mode.add_argument("--minutes", type=int, help="Set reminder minutes before start (enables reminders)")
    p_rem.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    p_rem.set_defaults(func=_cmd_outlook_reminders_set)

    # mail-list: read-only message listing (no search)
    # settings-apply: apply appointment settings from YAML rules across a window
    p_set = sub_out.add_parser("settings-apply", help="Apply appointment settings (categories/showAs/sensitivity/reminders) from YAML rules")
    _add_common_outlook_args(p_set)
    p_set.add_argument("--calendar", help="Calendar name to modify (defaults to primary)")
    p_set.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD (default: 30 days ago)")
    p_set.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD (default: 180 days ahead)")
    p_set.add_argument("--config", required=True, help="YAML with rules: settings: {defaults: {...}} rules: [{match: {...}, set: {...}}]")
    p_set.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    p_set.set_defaults(func=_cmd_outlook_settings_apply)

    p_mail = sub_out.add_parser("mail-list", help="List recent messages (read-only)")
    _add_common_outlook_args(p_mail)
    p_mail.add_argument("--folder", default="inbox", help="Mail folder (default: inbox)")
    p_mail.add_argument("--top", type=int, default=5, help="Items per page (default 5)")
    p_mail.add_argument("--pages", type=int, default=1, help="Pages to fetch (default 1)")
    p_mail.set_defaults(func=_cmd_outlook_mail_list)

    return p


def _add_common_outlook_args(sp: argparse.ArgumentParser) -> None:
    """Attach shared Outlook auth arguments to a subparser (delegates to cli.args)."""
    from .cli.args import add_common_outlook_args
    add_common_outlook_args(sp)
    
    

def _add_common_gmail_auth_args(sp: argparse.ArgumentParser) -> None:
    """Attach shared Gmail auth/cache arguments to a subparser (delegates to cli.args)."""
    from .cli.args import add_common_gmail_auth_args
    add_common_gmail_auth_args(sp)

def _add_common_gmail_paging_args(sp: argparse.ArgumentParser, *, default_days: int, default_pages: int, default_page_size: int) -> None:
    """Attach common paging/time-window arguments to a Gmail subparser (delegates)."""
    from .cli.args import add_common_gmail_paging_args
    add_common_gmail_paging_args(sp, default_days=default_days, default_pages=default_pages, default_page_size=default_page_size)


def _build_outlook_service(args: argparse.Namespace):
    """Create an OutlookService using shared resolver; returns None on failure."""
    try:
        return build_outlook_service(
            profile=getattr(args, "profile", None),
            client_id=getattr(args, "client_id", None),
            tenant=getattr(args, "tenant", None),
            token_path=getattr(args, "token", None),
        )
    except Exception as exc:
        print(str(exc))
        return None


def _cmd_outlook_mail_list(args: argparse.Namespace) -> int:
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


def _cmd_outlook_add(args: argparse.Namespace) -> int:
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


def _cmd_outlook_locations_enrich(args: argparse.Namespace) -> int:
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


def _cmd_outlook_calendar_share(args: argparse.Namespace) -> int:
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


def _cmd_outlook_schedule_import(args: argparse.Namespace) -> int:
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


def _cmd_outlook_add_recurring(args: argparse.Namespace) -> int:
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


def _cmd_outlook_add_from_config(args: argparse.Namespace) -> int:
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


def _cmd_outlook_verify_from_config(args: argparse.Namespace) -> int:
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


def _cmd_gmail_mail_list(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailMailListRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 7)),
        pages=int(getattr(args, "pages", 1)),
        page_size=int(getattr(args, "page_size", 10)),
        inbox_only=bool(getattr(args, "inbox_only", False)),
    )
    envelope = GmailMailListProcessor().process(GmailMailListRequestConsumer(request).consume())
    GmailMailListProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _cmd_gmail_sweep_top(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailSweepTopRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 10)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        inbox_only=bool(getattr(args, "inbox_only", True)),
        top=int(getattr(args, "top", 10)),
        out_path=Path(getattr(args, "out")) if getattr(args, "out", None) else None,
    )
    envelope = GmailSweepTopProcessor().process(GmailSweepTopRequestConsumer(request).consume())
    GmailSweepTopProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _cmd_outlook_update_locations_from_config(args: argparse.Namespace) -> int:
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


def _cmd_outlook_apply_locations_from_config(args: argparse.Namespace) -> int:
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


def _cmd_outlook_reminders_off(args: argparse.Namespace) -> int:
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


def _cmd_outlook_list_one_offs(args: argparse.Namespace) -> int:
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


def _cmd_outlook_reminders_set(args: argparse.Namespace) -> int:
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


def _cmd_outlook_settings_apply(args: argparse.Namespace) -> int:
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



def _cmd_outlook_dedup(args: argparse.Namespace) -> int:
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


def _cmd_outlook_remove_from_config(args: argparse.Namespace) -> int:
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


def _cmd_outlook_scan_classes(args: argparse.Namespace) -> int:
    from calendar_assistant.yamlio import dump_config

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


def _cmd_gmail_scan_classes(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailScanClassesRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 60)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        inbox_only=bool(getattr(args, "inbox_only", False)),
        calendar=getattr(args, "calendar", None),
        out_path=Path(getattr(args, "out")) if getattr(args, "out", None) else None,
    )
    envelope = GmailScanClassesProcessor().process(GmailScanClassesRequestConsumer(request).consume())
    GmailScanClassesProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _cmd_gmail_scan_receipts(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailReceiptsRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 365)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        calendar=getattr(args, "calendar", None),
        out_path=Path(getattr(args, "out")),
    )
    envelope = GmailReceiptsProcessor().process(GmailReceiptsRequestConsumer(request).consume())
    GmailPlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _cmd_gmail_scan_activerh(args: argparse.Namespace) -> int:
    """Generic targeting wrapper for ActiveRH receipts.

    Builds a broad query targeting Richmond Hill Active receipts and delegates to
    scan-receipts parser for class/range/time/location extraction.
    """
    from .gmail_service import GmailService
    # If user supplied a query, just reuse scan-receipts logic directly
    if getattr(args, "query", None):
        return _cmd_gmail_scan_receipts(args)
    # Construct via service helper and delegate
    q = GmailService.build_activerh_query(
        days=int(getattr(args, "days", 365)),
        explicit=None,
        programs=None,
        from_text=getattr(args, "from_text", None),
    )
    setattr(args, "query", q)
    return _cmd_gmail_scan_receipts(args)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
