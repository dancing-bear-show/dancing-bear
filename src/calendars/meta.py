from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="calendar",
    purpose="Outlook calendars + Gmail scans → plans",
    display_name="Calendar",
    bin_name="./bin/calendar",
    example_cmd="./bin/calendar outlook list-one-offs --calendar 'Your Family'",
)
