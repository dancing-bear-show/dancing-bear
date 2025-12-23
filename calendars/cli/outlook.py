from __future__ import annotations

"""Registration helper for Outlook calendar subcommands."""


def register(
    subparsers,
    *,
    f_add,
    f_add_recurring,
    f_add_from_config,
    f_verify_from_config,
    f_update_locations,
    f_apply_locations,
    f_locations_enrich,
    f_list_one_offs,
    f_remove_from_config,
    f_dedup,
    f_scan_classes,
    f_schedule_import,
    f_reminders_off,
    f_reminders_set,
    f_calendar_share,
    f_settings_apply,
    f_mail_list,
    add_common_outlook_args,
):
    """Register Outlook calendar subcommands under the 'outlook' subparser."""
    from .args import (
        HELP_START_DATE,
        HELP_END_DATE,
        HELP_CALENDAR_DEFAULT,
        HELP_CONFIG_EVENTS,
        HELP_DRY_RUN,
        HELP_DEFAULT_CALENDAR,
    )

    p_outlook = subparsers.add_parser("outlook", help="Outlook calendar operations")
    sub_out = p_outlook.add_subparsers(dest="outlook_cmd")

    # add: single event
    p_add = sub_out.add_parser("add", help="Add a one-time event to a calendar")
    add_common_outlook_args(p_add)
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
    p_add.set_defaults(func=f_add)

    # add-recurring
    p_rec = sub_out.add_parser("add-recurring", help="Add a recurring event with optional exclusions")
    add_common_outlook_args(p_rec)
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
    p_rec.set_defaults(func=f_add_recurring)

    # add-from-config
    p_cfg = sub_out.add_parser("add-from-config", help="Add events defined in a YAML file")
    add_common_outlook_args(p_cfg)
    p_cfg.add_argument("--config", required=True, help=HELP_CONFIG_EVENTS)
    p_cfg.add_argument("--dry-run", action="store_true", help="Print actions without creating events")
    p_cfg.add_argument("--no-reminder", action="store_true", help="Create events without reminders/alerts")
    p_cfg.set_defaults(func=f_add_from_config)

    # verify-from-config
    p_verify = sub_out.add_parser("verify-from-config", help="Verify plan against Outlook to avoid duplicates")
    add_common_outlook_args(p_verify)
    p_verify.add_argument("--config", required=True, help=HELP_CONFIG_EVENTS)
    p_verify.add_argument("--calendar", help=HELP_CALENDAR_DEFAULT)
    p_verify.set_defaults(func=f_verify_from_config)

    # update-locations
    p_update_loc = sub_out.add_parser("update-locations", help="Update YAML event locations from Outlook calendar")
    add_common_outlook_args(p_update_loc)
    p_update_loc.add_argument("--config", required=True, help=HELP_CONFIG_EVENTS)
    p_update_loc.add_argument("--calendar", help=HELP_CALENDAR_DEFAULT)
    p_update_loc.add_argument("--dry-run", action="store_true", help="Preview updates without writing")
    p_update_loc.set_defaults(func=f_update_locations)

    # apply-locations
    p_apply_loc = sub_out.add_parser("apply-locations", help="Apply locations from YAML to Outlook events")
    add_common_outlook_args(p_apply_loc)
    p_apply_loc.add_argument("--config", required=True, help="YAML events config path")
    p_apply_loc.add_argument("--calendar", help=HELP_CALENDAR_DEFAULT)
    p_apply_loc.add_argument("--dry-run", action="store_true", help="Preview updates without patching events")
    p_apply_loc.add_argument("--all-occurrences", action="store_true", help="Update all matching events in window (dedup by series)")
    p_apply_loc.set_defaults(func=f_apply_locations)

    # locations-enrich
    p_enrich_loc = sub_out.add_parser("locations-enrich", help="Enrich Outlook event locations with full addresses")
    add_common_outlook_args(p_enrich_loc)
    p_enrich_loc.add_argument("--calendar", required=True, help="Calendar name to scan/update")
    p_enrich_loc.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD")
    p_enrich_loc.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD")
    p_enrich_loc.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    p_enrich_loc.set_defaults(func=f_locations_enrich)

    # list-one-offs
    p_list_one = sub_out.add_parser("list-one-offs", help="List non-recurring (single) events in a calendar window")
    add_common_outlook_args(p_list_one)
    p_list_one.add_argument("--calendar", help="Calendar name (e.g., 'Your Family')")
    p_list_one.add_argument("--from", dest="from_date", help=HELP_START_DATE)
    p_list_one.add_argument("--to", dest="to_date", help=HELP_END_DATE)
    p_list_one.add_argument("--limit", type=int, default=200, help="How many rows to show (default 200)")
    p_list_one.add_argument("--out", help="Optional YAML output path (events: [])")
    p_list_one.set_defaults(func=f_list_one_offs)

    # remove-from-config
    p_rm_cfg = sub_out.add_parser("remove-from-config", help="Delete Outlook events/series matching a YAML config")
    add_common_outlook_args(p_rm_cfg)
    p_rm_cfg.add_argument("--config", required=True, help=HELP_CONFIG_EVENTS)
    p_rm_cfg.add_argument("--calendar", help=HELP_CALENDAR_DEFAULT)
    p_rm_cfg.add_argument("--apply", action="store_true", help="Actually delete; otherwise just plan")
    p_rm_cfg.add_argument("--subject-only", action="store_true", help="Match by subject only (ignore day/time)")
    p_rm_cfg.set_defaults(func=f_remove_from_config)

    # dedup
    p_dedup = sub_out.add_parser("dedup", help="Find and optionally remove duplicate series by subject/day/time")
    add_common_outlook_args(p_dedup)
    p_dedup.add_argument("--calendar", help="Calendar name (e.g., 'Your Family')")
    p_dedup.add_argument("--from", dest="from_date", help=HELP_START_DATE)
    p_dedup.add_argument("--to", dest="to_date", help=HELP_END_DATE)
    p_dedup.add_argument("--apply", action="store_true", help="Delete duplicates (keep oldest series by default)")
    p_dedup.add_argument("--delete-standardized", action="store_true", help="Prefer deleting series whose location looks standardized (address-style)")
    p_dedup.add_argument("--keep-newest", action="store_true", help="Keep newest series (default keeps oldest)")
    p_dedup.add_argument("--prefer-delete-nonstandard", action="store_true", help="Prefer deleting series with non-standard location (missing/empty)")
    p_dedup.set_defaults(func=f_dedup)

    # scan-classes
    p_scan = sub_out.add_parser("scan-classes", help="Scan recent emails for class schedules and output a plan")
    add_common_outlook_args(p_scan)
    p_scan.add_argument("--from-text", dest="from_text", default="active rh", help="Text to match sender (used in $search)")
    p_scan.add_argument("--days", type=int, default=60, help="Look back N days (default 60)")
    p_scan.add_argument("--top", type=int, default=25, help="Items per page (default 25)")
    p_scan.add_argument("--pages", type=int, default=2, help="Max pages to fetch (default 2)")
    p_scan.add_argument("--out", help="Optional output YAML plan path (events: [])")
    p_scan.add_argument("--calendar", help=HELP_DEFAULT_CALENDAR)
    p_scan.set_defaults(func=f_scan_classes)

    # schedule-import
    p_sched = sub_out.add_parser("schedule-import", help="Import schedule file/URL and create a calendar of events")
    add_common_outlook_args(p_sched)
    p_sched.add_argument("--calendar", help="New or existing calendar name (default: Imported Schedules)")
    p_sched.add_argument("--source", required=True, help="Path or URL to schedule (csv/xlsx/pdf/website)")
    p_sched.add_argument("--kind", choices=["auto", "csv", "xlsx", "pdf", "website"], default="auto", help="Source type (default: auto)")
    p_sched.add_argument("--tz", help="Time zone for events (IANA/Windows). Defaults to mailbox")
    p_sched.add_argument("--until", help="Global end date YYYY-MM-DD for recurring series (overrides parsed range)")
    p_sched.add_argument("--dry-run", action="store_true", help="Preview creates without writing")
    p_sched.add_argument("--no-reminder", action="store_true", help="Create events without reminders/alerts")
    p_sched.set_defaults(func=f_schedule_import)

    # reminders-off
    p_rem = sub_out.add_parser("reminders-off", help="Turn off reminders for events in a date window")
    add_common_outlook_args(p_rem)
    p_rem.add_argument("--calendar", help="Calendar name to update (defaults to primary)")
    p_rem.add_argument("--from", dest="from_date", default=None, help=HELP_START_DATE)
    p_rem.add_argument("--to", dest="to_date", default=None, help=HELP_END_DATE)
    p_rem.add_argument("--all-occurrences", action="store_true", help="Also update occurrences (not just series masters)")
    p_rem.add_argument("--dry-run", action="store_true", help="Preview changes without patching events")
    p_rem.set_defaults(func=f_reminders_off)

    # reminders-set
    p_rem_set = sub_out.add_parser("reminders-set", help="Set reminders on/off or minutes for events in a date window")
    add_common_outlook_args(p_rem_set)
    p_rem_set.add_argument("--calendar", required=True, help="Calendar name to modify")
    p_rem_set.add_argument("--from", dest="from_date", help=HELP_START_DATE)
    p_rem_set.add_argument("--to", dest="to_date", help=HELP_END_DATE)
    mode = p_rem_set.add_mutually_exclusive_group(required=True)
    mode.add_argument("--off", action="store_true", help="Turn reminders off for matching events")
    mode.add_argument("--minutes", type=int, help="Set reminder minutes before start (enables reminders)")
    p_rem_set.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    p_rem_set.set_defaults(func=f_reminders_set)

    # calendar-share
    p_share = sub_out.add_parser("calendar-share", help="Share a calendar with a recipient (set permission role)")
    add_common_outlook_args(p_share)
    p_share.add_argument("--calendar", required=True, help="Calendar name (e.g., 'Activities')")
    p_share.add_argument("--with", dest="recipient", required=True, help="Email address to share with")
    p_share.add_argument("--role", default="write", help="Role: read|write|limitedRead|freeBusyRead|delegate… (default: write)")
    p_share.set_defaults(func=f_calendar_share)

    # settings-apply
    p_set = sub_out.add_parser("settings-apply", help="Apply appointment settings (categories/showAs/sensitivity/reminders) from YAML rules")
    add_common_outlook_args(p_set)
    p_set.add_argument("--calendar", help="Calendar name to modify (defaults to primary)")
    p_set.add_argument("--from", dest="from_date", help=HELP_START_DATE)
    p_set.add_argument("--to", dest="to_date", help=HELP_END_DATE)
    p_set.add_argument("--config", required=True, help="YAML with rules: settings: {defaults: {...}} rules: [{match: {...}, set: {...}}]")
    p_set.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    p_set.set_defaults(func=f_settings_apply)

    # mail-list
    p_mail = sub_out.add_parser("mail-list", help="List recent messages (read-only)")
    add_common_outlook_args(p_mail)
    p_mail.add_argument("--folder", default="inbox", help="Mail folder (default: inbox)")
    p_mail.add_argument("--top", type=int, default=5, help="Items per page (default 5)")
    p_mail.add_argument("--pages", type=int, default=1, help="Pages to fetch (default 1)")
    p_mail.set_defaults(func=f_mail_list)

    return p_outlook
