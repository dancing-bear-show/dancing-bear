"""Calendar Assistant CLI entrypoint.

Wires the public CLI and delegates to focused command handlers. Small OO
helpers (e.g., OutlookContext) centralize configuration to reduce duplication
without changing flags or subcommands.
"""

from __future__ import annotations

import argparse
from typing import Optional

from core.assistant import BaseAssistant

from .cli.args import (
    add_common_outlook_args,
    add_common_gmail_auth_args,
    add_common_gmail_paging_args,
)
from .cli.outlook import register as register_outlook
from .cli.gmail import register as register_gmail

from .outlook.commands import (
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
from .gmail.commands import (
    run_gmail_scan_classes,
    run_gmail_scan_receipts,
    run_gmail_scan_activerh,
    run_gmail_mail_list,
    run_gmail_sweep_top,
)

# Backward-compatible aliases for tests that import from __main__
_cmd_outlook_add = run_outlook_add
_cmd_outlook_add_recurring = run_outlook_add_recurring
_cmd_outlook_add_from_config = run_outlook_add_from_config
_cmd_outlook_verify_from_config = run_outlook_verify_from_config
_cmd_outlook_update_locations_from_config = run_outlook_update_locations
_cmd_outlook_apply_locations_from_config = run_outlook_apply_locations
_cmd_outlook_locations_enrich = run_outlook_locations_enrich
_cmd_outlook_list_one_offs = run_outlook_list_one_offs
_cmd_outlook_remove_from_config = run_outlook_remove_from_config
_cmd_outlook_dedup = run_outlook_dedup
_cmd_outlook_scan_classes = run_outlook_scan_classes
_cmd_outlook_schedule_import = run_outlook_schedule_import
_cmd_outlook_reminders_off = run_outlook_reminders_off
_cmd_outlook_reminders_set = run_outlook_reminders_set
_cmd_outlook_calendar_share = run_outlook_calendar_share
_cmd_outlook_settings_apply = run_outlook_settings_apply
_cmd_outlook_mail_list = run_outlook_mail_list
_cmd_gmail_scan_classes = run_gmail_scan_classes
_cmd_gmail_scan_receipts = run_gmail_scan_receipts
_cmd_gmail_scan_activerh = run_gmail_scan_activerh
_cmd_gmail_mail_list = run_gmail_mail_list
_cmd_gmail_sweep_top = run_gmail_sweep_top


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
    p = argparse.ArgumentParser(
        description="Calendar Assistant CLI",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    assistant.add_agentic_flags(p)
    p.add_argument("--profile", help="Credentials profile (INI section suffix, e.g., outlook_personal)")
    sub = p.add_subparsers(dest="command")

    # Register Outlook subcommands
    register_outlook(
        sub,
        f_add=run_outlook_add,
        f_add_recurring=run_outlook_add_recurring,
        f_add_from_config=run_outlook_add_from_config,
        f_verify_from_config=run_outlook_verify_from_config,
        f_update_locations=run_outlook_update_locations,
        f_apply_locations=run_outlook_apply_locations,
        f_locations_enrich=run_outlook_locations_enrich,
        f_list_one_offs=run_outlook_list_one_offs,
        f_remove_from_config=run_outlook_remove_from_config,
        f_dedup=run_outlook_dedup,
        f_scan_classes=run_outlook_scan_classes,
        f_schedule_import=run_outlook_schedule_import,
        f_reminders_off=run_outlook_reminders_off,
        f_reminders_set=run_outlook_reminders_set,
        f_calendar_share=run_outlook_calendar_share,
        f_settings_apply=run_outlook_settings_apply,
        f_mail_list=run_outlook_mail_list,
        add_common_outlook_args=add_common_outlook_args,
    )

    # Register Gmail subcommands
    register_gmail(
        sub,
        f_scan_classes=run_gmail_scan_classes,
        f_scan_receipts=run_gmail_scan_receipts,
        f_scan_activerh=run_gmail_scan_activerh,
        f_mail_list=run_gmail_mail_list,
        f_sweep_top=run_gmail_sweep_top,
        add_common_gmail_auth_args=add_common_gmail_auth_args,
        add_common_gmail_paging_args=add_common_gmail_paging_args,
    )

    return p


def _lazy_agentic():
    """Lazy loader for agentic capsule builder."""
    from .agentic import build_agentic_capsule
    return build_agentic_capsule


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
