from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="schedule",
    purpose="Generate/verify/apply calendar plans (dry-run first)",
    display_name="Schedule",
    bin_name="./bin/schedule-assistant",
    example_cmd="./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml",
)
