"""Calendar Assistant CLI using CLIApp framework.

Commands:
  outlook add|add-recurring|add-from-config|verify-from-config|...
  gmail scan-classes|scan-receipts|scan-activerh|...

All processing is local-first with dry-run/plan-then-apply patterns.
"""

from __future__ import annotations

from typing import Optional, List

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .args import (
    HELP_START_DATE,
    HELP_END_DATE,
    HELP_CALENDAR_DEFAULT,
    HELP_CONFIG_EVENTS,
    HELP_DRY_RUN,
    HELP_DEFAULT_CALENDAR,
    HELP_INBOX_ONLY,
)
from ..outlook.commands import (
    run_outlook_add,
    run_outlook_add_recurring,
    run_outlook_add_from_config,
    run_outlook_verify_from_config,
    run_outlook_update_locations,
    run_outlook_apply_locations,
    run_outlook_locations_enrich,
    run_outlook_list_one_offs,
    run_outlook_remove_from_config,
    run_outlook_dedup,
    run_outlook_scan_classes,
    run_outlook_schedule_import,
    run_outlook_reminders_off,
    run_outlook_reminders_set,
    run_outlook_calendar_share,
    run_outlook_settings_apply,
    run_outlook_mail_list,
)
from ..gmail.commands import (
    run_gmail_scan_classes,
    run_gmail_scan_receipts,
    run_gmail_scan_activerh,
    run_gmail_mail_list,
    run_gmail_sweep_top,
)

assistant = BaseAssistant(
    "calendar",
    "agentic: calendar\npurpose: Outlook calendars + Gmail scans → plans",
)

app = CLIApp(
    "calendar-assistant",
    "Calendar Assistant CLI for Outlook calendars and Gmail scans",
    add_common_args=False,
)


def _lazy_agentic():
    """Lazy loader for agentic capsule builder."""
    from .agentic import build_agentic_capsule
    return build_agentic_capsule


# --- outlook group ---
outlook_group = app.group("outlook", help="Outlook calendar operations")


# Common outlook auth args as a helper
def _outlook_args(cmd):
    """Add common Outlook auth arguments to a command."""
    cmd = outlook_group.argument("--client-id", help="Azure app (client) ID")(cmd)
    cmd = outlook_group.argument("--tenant", default="consumers", help="AAD tenant")(cmd)
    cmd = outlook_group.argument("--token", help="Path to token cache JSON")(cmd)
    return cmd


@outlook_group.command("add", help="Add a one-time event to a calendar")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name (defaults to primary)")
@outlook_group.argument("--subject", required=True, help="Event subject/title")
@outlook_group.argument("--start", required=True, help="Start datetime ISO")
@outlook_group.argument("--end", required=True, help="End datetime ISO")
@outlook_group.argument("--tz", help="Time zone (IANA or Windows)")
@outlook_group.argument("--location", help="Location display name")
@outlook_group.argument("--body-html", dest="body_html", help="HTML body content")
@outlook_group.argument("--all-day", action="store_true", help="Mark as all-day")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
@outlook_group.argument("--reminder-minutes", type=int, help="Reminder minutes before start")
def cmd_outlook_add(args) -> int:
    return run_outlook_add(args)


@outlook_group.command("add-recurring", help="Add a recurring event with optional exclusions")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name (defaults to primary)")
@outlook_group.argument("--subject", required=True, help="Event subject")
@outlook_group.argument("--repeat", required=True, choices=["daily", "weekly", "monthly"], help="Recurrence type")
@outlook_group.argument("--interval", type=int, default=1, help="Recurrence interval")
@outlook_group.argument("--byday", help="Days for weekly (e.g., MO,WE,FR)")
@outlook_group.argument("--range-start", required=True, dest="range_start", help="Start date YYYY-MM-DD")
@outlook_group.argument("--until", help="End date YYYY-MM-DD")
@outlook_group.argument("--count", type=int, help="Occurrences count")
@outlook_group.argument("--start-time", required=True, help="Start time HH:MM[:SS]")
@outlook_group.argument("--end-time", required=True, help="End time HH:MM[:SS]")
@outlook_group.argument("--tz", help="Time zone (IANA or Windows)")
@outlook_group.argument("--location", help="Location display name")
@outlook_group.argument("--body-html", dest="body_html", help="HTML body content")
@outlook_group.argument("--exdates", help="Comma-separated YYYY-MM-DD dates to exclude")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
@outlook_group.argument("--reminder-minutes", type=int, help="Reminder minutes before start")
def cmd_outlook_add_recurring(args) -> int:
    return run_outlook_add_recurring(args)


@outlook_group.command("add-from-config", help="Add events defined in a YAML file")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help=HELP_CONFIG_EVENTS)
@outlook_group.argument("--dry-run", action="store_true", help="Preview without creating")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
def cmd_outlook_add_from_config(args) -> int:
    return run_outlook_add_from_config(args)


@outlook_group.command("verify-from-config", help="Verify plan against Outlook to avoid duplicates")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help=HELP_CONFIG_EVENTS)
@outlook_group.argument("--calendar", help=HELP_CALENDAR_DEFAULT)
def cmd_outlook_verify_from_config(args) -> int:
    return run_outlook_verify_from_config(args)


@outlook_group.command("update-locations", help="Update YAML event locations from Outlook calendar")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help=HELP_CONFIG_EVENTS)
@outlook_group.argument("--calendar", help=HELP_CALENDAR_DEFAULT)
@outlook_group.argument("--dry-run", action="store_true", help="Preview without writing")
def cmd_outlook_update_locations(args) -> int:
    return run_outlook_update_locations(args)


@outlook_group.command("apply-locations", help="Apply locations from YAML to Outlook events")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help="YAML events config path")
@outlook_group.argument("--calendar", help=HELP_CALENDAR_DEFAULT)
@outlook_group.argument("--dry-run", action="store_true", help="Preview without patching")
@outlook_group.argument("--all-occurrences", action="store_true", help="Update all matching events")
def cmd_outlook_apply_locations(args) -> int:
    return run_outlook_apply_locations(args)


@outlook_group.command("locations-enrich", help="Enrich Outlook event locations with full addresses")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", required=True, help="Calendar name to scan/update")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
def cmd_outlook_locations_enrich(args) -> int:
    return run_outlook_locations_enrich(args)


@outlook_group.command("list-one-offs", help="List non-recurring events in a calendar window")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--limit", type=int, default=200, help="Max rows (default 200)")
@outlook_group.argument("--out", help="Optional YAML output path")
def cmd_outlook_list_one_offs(args) -> int:
    return run_outlook_list_one_offs(args)


@outlook_group.command("remove-from-config", help="Delete Outlook events/series matching a YAML config")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--config", required=True, help=HELP_CONFIG_EVENTS)
@outlook_group.argument("--calendar", help=HELP_CALENDAR_DEFAULT)
@outlook_group.argument("--apply", action="store_true", help="Actually delete; otherwise just plan")
@outlook_group.argument("--subject-only", action="store_true", help="Match by subject only")
def cmd_outlook_remove_from_config(args) -> int:
    return run_outlook_remove_from_config(args)


@outlook_group.command("dedup", help="Find and optionally remove duplicate series")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--apply", action="store_true", help="Delete duplicates")
@outlook_group.argument("--delete-standardized", action="store_true", help="Prefer deleting standardized locations")
@outlook_group.argument("--keep-newest", action="store_true", help="Keep newest series")
@outlook_group.argument("--prefer-delete-nonstandard", action="store_true", help="Prefer deleting non-standard locations")
def cmd_outlook_dedup(args) -> int:
    return run_outlook_dedup(args)


@outlook_group.command("scan-classes", help="Scan recent emails for class schedules")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--from-text", dest="from_text", default="active rh", help="Sender text to match")
@outlook_group.argument("--days", type=int, default=60, help="Look back N days")
@outlook_group.argument("--top", type=int, default=25, help="Items per page")
@outlook_group.argument("--pages", type=int, default=2, help="Max pages")
@outlook_group.argument("--out", help="Optional output YAML plan path")
@outlook_group.argument("--calendar", help=HELP_DEFAULT_CALENDAR)
def cmd_outlook_scan_classes(args) -> int:
    return run_outlook_scan_classes(args)


@outlook_group.command("schedule-import", help="Import schedule file/URL and create calendar events")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name (default: Imported Schedules)")
@outlook_group.argument("--source", required=True, help="Path or URL to schedule")
@outlook_group.argument("--kind", choices=["auto", "csv", "xlsx", "pdf", "website"], default="auto", help="Source type")
@outlook_group.argument("--tz", help="Time zone for events")
@outlook_group.argument("--until", help="Global end date YYYY-MM-DD")
@outlook_group.argument("--dry-run", action="store_true", help="Preview without writing")
@outlook_group.argument("--no-reminder", action="store_true", help="No reminders")
def cmd_outlook_schedule_import(args) -> int:
    return run_outlook_schedule_import(args)


@outlook_group.command("reminders-off", help="Turn off reminders for events in a date window")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--all-occurrences", action="store_true", help="Also update occurrences")
@outlook_group.argument("--dry-run", action="store_true", help="Preview changes")
def cmd_outlook_reminders_off(args) -> int:
    return run_outlook_reminders_off(args)


@outlook_group.command("reminders-set", help="Set reminders on/off or minutes for events")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", required=True, help="Calendar name")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--off", action="store_true", help="Turn reminders off")
@outlook_group.argument("--minutes", type=int, help="Set reminder minutes")
@outlook_group.argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
def cmd_outlook_reminders_set(args) -> int:
    return run_outlook_reminders_set(args)


@outlook_group.command("calendar-share", help="Share a calendar with a recipient")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", required=True, help="Calendar name")
@outlook_group.argument("--with", dest="recipient", required=True, help="Email address to share with")
@outlook_group.argument("--role", default="write", help="Role: read|write|limitedRead|freeBusyRead|delegate")
def cmd_outlook_calendar_share(args) -> int:
    return run_outlook_calendar_share(args)


@outlook_group.command("settings-apply", help="Apply appointment settings from YAML rules")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--calendar", help="Calendar name")
@outlook_group.argument("--from", dest="from_date", help=HELP_START_DATE)
@outlook_group.argument("--to", dest="to_date", help=HELP_END_DATE)
@outlook_group.argument("--config", required=True, help="YAML with rules")
@outlook_group.argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
def cmd_outlook_settings_apply(args) -> int:
    return run_outlook_settings_apply(args)


@outlook_group.command("mail-list", help="List recent messages (read-only)")
@outlook_group.argument("--client-id", help="Azure app (client) ID")
@outlook_group.argument("--tenant", default="consumers", help="AAD tenant")
@outlook_group.argument("--token", help="Path to token cache JSON")
@outlook_group.argument("--folder", default="inbox", help="Mail folder (default: inbox)")
@outlook_group.argument("--top", type=int, default=5, help="Items per page")
@outlook_group.argument("--pages", type=int, default=1, help="Pages to fetch")
def cmd_outlook_mail_list(args) -> int:
    return run_outlook_mail_list(args)


# --- gmail group ---
gmail_group = app.group("gmail", help="Gmail scan helpers for calendar")


@gmail_group.command("scan-classes", help="Scan recent Gmail for class schedules")
@gmail_group.argument("--credentials", help="Path to OAuth credentials.json")
@gmail_group.argument("--token", help="Path to token.json")
@gmail_group.argument("--cache", help="Cache directory")
@gmail_group.argument("--from-text", dest="from_text", default="active rh", help="Sender text to match")
@gmail_group.argument("--query", help="Raw Gmail query")
@gmail_group.argument("--days", type=int, default=60, help="Look back N days")
@gmail_group.argument("--pages", type=int, default=5, help="Max pages")
@gmail_group.argument("--page-size", type=int, default=100, help="Page size")
@gmail_group.argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
@gmail_group.argument("--out", help="Optional output YAML plan path")
@gmail_group.argument("--calendar", help=HELP_DEFAULT_CALENDAR)
def cmd_gmail_scan_classes(args) -> int:
    return run_gmail_scan_classes(args)


@gmail_group.command("scan-receipts", help="Scan Gmail receipts and extract recurring events")
@gmail_group.argument("--credentials", help="Path to OAuth credentials.json")
@gmail_group.argument("--token", help="Path to token.json")
@gmail_group.argument("--cache", help="Cache directory")
@gmail_group.argument("--from-text", dest="from_text", default="richmondhill.ca", help="Sender filter")
@gmail_group.argument("--query", help="Raw Gmail query")
@gmail_group.argument("--days", type=int, default=365, help="Look back N days")
@gmail_group.argument("--pages", type=int, default=5, help="Max pages")
@gmail_group.argument("--page-size", type=int, default=100, help="Page size")
@gmail_group.argument("--out", required=True, help="Output YAML plan path")
@gmail_group.argument("--calendar", help=HELP_DEFAULT_CALENDAR)
def cmd_gmail_scan_receipts(args) -> int:
    return run_gmail_scan_receipts(args)


@gmail_group.command("scan-activerh", help="Generic scan for ActiveRH receipts")
@gmail_group.argument("--credentials", help="Path to OAuth credentials.json")
@gmail_group.argument("--token", help="Path to token.json")
@gmail_group.argument("--cache", help="Cache directory")
@gmail_group.argument("--query", help="Raw Gmail query")
@gmail_group.argument("--days", type=int, default=365, help="Look back N days")
@gmail_group.argument("--pages", type=int, default=10, help="Max pages")
@gmail_group.argument("--page-size", type=int, default=100, help="Page size")
@gmail_group.argument("--out", required=True, help="Output YAML plan path")
@gmail_group.argument("--calendar", help=HELP_DEFAULT_CALENDAR)
def cmd_gmail_scan_activerh(args) -> int:
    return run_gmail_scan_activerh(args)


@gmail_group.command("mail-list", help="List recent Gmail messages (read-only)")
@gmail_group.argument("--credentials", help="Path to OAuth credentials.json")
@gmail_group.argument("--token", help="Path to token.json")
@gmail_group.argument("--cache", help="Cache directory")
@gmail_group.argument("--from-text", dest="from_text", help="Optional sender filter")
@gmail_group.argument("--query", help="Raw Gmail query")
@gmail_group.argument("--days", type=int, default=7, help="Look back N days")
@gmail_group.argument("--pages", type=int, default=1, help="Max pages")
@gmail_group.argument("--page-size", type=int, default=10, help="Page size")
@gmail_group.argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
def cmd_gmail_mail_list(args) -> int:
    return run_gmail_mail_list(args)


@gmail_group.command("sweep-top", help="Find top frequent senders in Inbox")
@gmail_group.argument("--credentials", help="Path to OAuth credentials.json")
@gmail_group.argument("--token", help="Path to token.json")
@gmail_group.argument("--cache", help="Cache directory")
@gmail_group.argument("--days", type=int, default=10, help="Look back N days")
@gmail_group.argument("--pages", type=int, default=5, help="Max pages")
@gmail_group.argument("--page-size", type=int, default=100, help="Page size")
@gmail_group.argument("--top", type=int, default=10, help="How many top senders")
@gmail_group.argument("--inbox-only", action="store_true", help=HELP_INBOX_ONLY)
@gmail_group.argument("--out", help="Optional suggested filters YAML path")
def cmd_gmail_sweep_top(args) -> int:
    return run_gmail_sweep_top(args)


def _add_profile_arg(parser) -> None:
    """Add --profile argument to parser."""
    parser.add_argument("--profile", help="Credentials profile (INI section suffix)")


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the Calendar Assistant CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=lambda fmt, compact: (print(_lazy_agentic()()), 0)[1],
        argv=argv,
        post_build_hook=_add_profile_arg,
    )


if __name__ == "__main__":
    raise SystemExit(main())
